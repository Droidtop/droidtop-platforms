#!/usr/bin/env python3
"""Generate plugins/index.json: what every enginehost plugin repository has published.

Enginehost reads this ONE file from raw.githubusercontent.com before it asks
GitHub's API anything.  The API allows 60 requests an hour to an
unauthenticated address; a refresh across the plugin repositories costs more
than a tenth of that, so a few refreshes from one address (a fresh emulator
instance, a shared connection) spent the allowance and the catalog came up
empty.  Here the same listing is done once, by a workflow that has a token,
and every device reads the result from a host with no API allowance at all.

The index is a SNAPSHOT and says when it was made: enginehost falls back to
the per-origin API path for any origin this file does not name, and for the
whole file once it is older than a few days.

Nothing a repository says about itself is taken on trust, and neither is the
`plugin-published` dispatch that asks for a run: a dispatch only names a
repository to look at.  What enters the index is what this script verified
from the repository's own releases -- every bundle's signed manifest, the key
that signed it, the origin it names, and (when a release is first admitted)
that its native code covers both arm64-v8a and x86_64.  A repository that
validates and is not registered yet is registered in plugins/origins.json by
the same run.  Official repositories prove themselves with a key the offline
Enginehost root certified; listed third parties (plugins/third-party.json)
with a registration signed by a key their list entry names.  The threat model
is Droidtop/enginehost docs/security/2026-09-25-third-party-catalog.md.

Signature format v1 (Droidtop/tracker#550): a release envelope entry may
carry `jws`, a JWS whose certificate chain ends at the Enginehost signing
root's public key, which Enginehost pins (the owner derives that root from
Droidtop Core; Core itself is pinned nowhere).  With ENGINEHOST_TOOLING
pointing at a checkout of Droidtop/enginehost (its scripts/ and
app/src/main/assets/trust/, pinned by the workflow), such an entry is verified
to the root and needs no legacy signature, and a repository's
enginehost-signing-certificate.pem is published in its entry as `certificates`
once it verifies to the root for that origin.  The legacy key document stays
required: registration and the key history are keyed on it until the legacy
format is retired.  Without the tooling, or while Enginehost pins no root, only
the legacy signature is checked.

Run:
  plugins_index.py                 rebuild, write index.json/origins.json when changed
  plugins_index.py --event         the same, plus whatever the triggering GitHub
                                   event announces (a dispatch, a registration issue)
  plugins_index.py --check         validate the committed files offline (CI on a push)

GH_TOKEN, when set, raises the API allowance; public repositories are
readable without it.  Signatures are checked with the openssl command line,
which every GitHub runner has, so the job installs nothing.
"""

import argparse
import base64
import json
import os
import pathlib
import re
import sys
import urllib.error
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import jws  # noqa: E402
from common import Rejected, log, sha256_hex, warn  # noqa: E402
from envelopes import check_envelope, check_envelope_packs, digest_of, previous_envelopes, stream_of, write_envelope_packs  # noqa: E402
from fetch import download, releases, repository_file  # noqa: E402
from keys import certificate_serial, key_document, official_root, origin_of, owner_of  # noqa: E402
from layout import ALGORITHM, HISTORY_PATH, INDEX_PATH, KEY_DOCUMENT, OFFICIAL_OWNER, ORIGINS_PATH, PLUGINS_DIR, REFRESH_AFTER, RELEASE_ENVELOPES, REPO_NAME, REVOCATIONS_PATH, SCHEMA_VERSION, SIGNING_CERTIFICATE  # noqa: E402
from registry import check_history, load_history, load_third_party, recorded_key, registration_of  # noqa: E402


def v1_tooling():
    """(bundle_jws module, the Enginehost signing root's public key as SubjectPublicKeyInfo DER) from ENGINEHOST_TOOLING."""
    bundle_jws = jws.bundle_jws(required=False)
    if bundle_jws is None:
        return None, None
    tooling = pathlib.Path(os.environ["ENGINEHOST_TOOLING"])
    root_path = tooling / "app/src/main/assets/trust/enginehost-root.pub"
    if not root_path.is_file():
        warn("Enginehost pins no signing root key yet; format v1 signatures are not checked")
        return bundle_jws, None
    return bundle_jws, bundle_jws.pem_public_key(root_path.read_text(encoding="utf-8"))


class KeptRegistration(Rejected):
    """Not indexed this run, but the registration and its pin stand."""


# --- official keys ------------------------------------------------------------


def official_key(repo, document, key, pin):
    """Which key an official repository is indexed under, and whether that is a change.

    [document]/[key] is what the repository publishes now; [pin] is what
    origins.json registered ({keySha256, keySerial, key: the certified
    document from key-history.json}) or None.  Answers (document, key,
    serial, change), change being "registered", "rotated" or None.  A key
    the repository publishes is taken only with the root's certificate for
    this origin, and in place of a registered key only with a higher serial
    (T7, T10 of the threat model); otherwise the registered key stays and
    releases signed by the other key are left out.
    """
    serial = certificate_serial(document, OFFICIAL_ROOT)
    if pin is None:
        if serial is None:
            raise Rejected(repo + ": its key is not certified by the Enginehost root for " + origin_of(repo))
        return document, key, serial, "registered"
    pinned = pin["keySha256"].upper()
    pinned_serial = pin.get("keySerial", 0)
    if key.sha256 == pinned:
        if serial is None:
            raise Rejected(repo + ": its registered key no longer carries a valid root certificate")
        return document, key, serial, None
    if serial is not None and serial > pinned_serial:
        return document, key, serial, "rotated"
    warn(
        repo + " publishes key " + key.sha256 + " (serial " + str(serial) + ") in place of " + pinned
        + " (serial " + str(pinned_serial) + "): not a certified rotation; keeping the registered key"
    )
    if pin.get("key") is None:
        raise Rejected(repo + ": publishes an unaccepted key and its registered key's document is not on record")
    kept, kept_key = key_document(json.dumps(pin["key"]).encode(), origin_of(repo), repo + " registered key")
    if kept_key.sha256 != pinned or certificate_serial(kept, OFFICIAL_ROOT) is None:
        raise Rejected(repo + ": the key history's document for " + pinned + " does not verify")
    return kept, kept_key, pinned_serial, None


def index_for(repo, trust, pin, maintainer, previous):
    """One repository's entry: its verified releases, its key, and what was left out.

    [pin] is what origins.json registered for the repository (see
    official_key), or None when it is not registered yet.  For a third party
    it is the key its registration names, which the caller has already held
    to the list.  [previous] maps tag -> envelope sha256 from the committed
    index: a release already admitted with the same envelope is not held to
    the ABI rule again, so the rule governs what is published from now on and
    builds devices already run do not vanish.

    Answers (entry, record for origins.json, change or None, refused releases).
    """
    origin = origin_of(repo)
    third_party = trust == "third-party"
    listed = list(releases(repo))

    # The key: the repository's key document, from its newest release that
    # carries one (the build attaches it to every release) or its tree.
    documents = []
    for release in listed:
        asset = next((a for a in release.get("assets") or [] if a["name"] == KEY_DOCUMENT), None)
        if asset is not None:
            documents.append(download(asset["browser_download_url"]))
            break
    if not documents:
        tree_copy = repository_file(repo, KEY_DOCUMENT)
        if tree_copy is not None:
            documents.append(tree_copy)
    if not documents:
        raise Rejected(repo + " publishes no " + KEY_DOCUMENT)
    document, key = key_document(documents[0], origin, repo + " " + KEY_DOCUMENT)
    if third_party:
        if key.sha256 != pin["keySha256"].upper():
            raise Rejected(repo + " publishes key " + key.sha256 + " but registered " + pin["keySha256"])
        serial, change = 0, None
    else:
        document, key, serial, change = official_key(repo, document, key, pin)

    entry = {"repo": repo, "origin": origin, "trust": trust}
    if third_party:
        # A third party's key document is rebuilt from what was verified, so
        # nothing it chose to add (an `issuer` claim, say) reaches a device.
        entry["maintainer"] = {"id": maintainer["id"], "name": maintainer["name"]}
        entry["key"] = {
            "formatVersion": 1,
            "origin": origin,
            "algorithm": ALGORITHM,
            "publicKeySpki": key.spki_b64,
            "keySha256": key.sha256,
        }
    else:
        entry["key"] = document
        certificates = signing_certificates(repo, listed, origin)
        if certificates:
            entry["certificates"] = certificates
    entry["releases"] = []
    # The admitted envelopes' text, for the repository's pack; popped before
    # the entry is written.
    entry["_pack"] = {}
    refused = []
    for release in listed:
        assets = release.get("assets") or []
        envelope_asset = next((a for a in assets if a["name"] in RELEASE_ENVELOPES), None)
        if envelope_asset is None:
            # A release with no envelope is not a plugin release; enginehost
            # skips it too.
            continue
        body = download(envelope_asset["browser_download_url"])
        body_sha = sha256_hex(body)
        try:
            envelope = check_envelope(
                body, origin, key, assets, third_party, previous.get(release["tag_name"]) == body_sha, (JWS, SIGNING_ROOT)
            )
        except Rejected as reason:
            refused.append(release["tag_name"] + ": " + str(reason))
            continue
        entry["_pack"][body_sha] = body.decode("utf-8")
        listed_assets = []
        for asset in assets:
            listed_assets.append(
                {
                    "name": asset["name"],
                    "url": asset["browser_download_url"],
                    "size": asset.get("size", 0),
                    "sha256": body_sha if asset is envelope_asset else digest_of(asset),
                }
            )
        entry["releases"].append(
            {
                "tag": release["tag_name"],
                "stream": stream_of(release, envelope),
                "prerelease": bool(release.get("prerelease")),
                "published_at": release.get("published_at"),
                "assets": listed_assets,
            }
        )
    record = {"repo": repo, "keySha256": key.sha256}
    if not third_party:
        record["keySerial"] = serial
    return entry, record, change, refused


def signing_certificates(repo, listed, origin):
    """
    The repository's format-v1 signing certificate chain (x5c style: standard
    base64 DER, leaf first), from its newest release carrying one or its tree,
    when it verifies to the signing root for this origin; else []. Enginehost
    verifies it again before it makes the origin official.
    """
    if JWS is None or SIGNING_ROOT is None:
        return []
    text = None
    for release in listed:
        asset = next((a for a in release.get("assets") or [] if a["name"] == SIGNING_CERTIFICATE), None)
        if asset is not None:
            text = download(asset["browser_download_url"]).decode("utf-8", errors="replace")
            break
    if text is None:
        tree_copy = repository_file(repo, SIGNING_CERTIFICATE)
        text = tree_copy.decode("utf-8", errors="replace") if tree_copy is not None else None
    if text is None:
        return []
    try:
        chain = JWS.pem_certificates(text)
        named = JWS.verify_chain(chain, "plugin", SIGNING_ROOT)
    except JWS.Refused as reason:
        warn(repo + ": " + SIGNING_CERTIFICATE + " does not verify to the Enginehost signing root: " + str(reason))
        return []
    if JWS.origin_id(origin) not in named["origins"]:
        warn(repo + ": " + SIGNING_CERTIFICATE + " does not name " + origin)
        return []
    return [base64.b64encode(der).decode("ascii") for der in chain]


def check_revocations():
    """plugins/revocations.jws, when committed: a revocation list for "enginehost" signed under the signing root."""
    if not REVOCATIONS_PATH.is_file():
        return
    if JWS is None or SIGNING_ROOT is None:
        sys.exit("plugins/revocations.jws is committed but this run cannot verify it (no ENGINEHOST_TOOLING or no signing root)")
    try:
        named = JWS.verify(REVOCATIONS_PATH.read_text(encoding="ascii"), "revocations", SIGNING_ROOT, None)
    except JWS.Refused as reason:
        sys.exit("plugins/revocations.jws does not verify: " + str(reason))
    payload = json.loads(named["payload"])
    if "enginehost" not in named["catalogs"] or payload.get("catalog") != "enginehost" \
            or payload.get("type") != "droidtop-revocations" or payload.get("version") != 1:
        sys.exit("plugins/revocations.jws is not Enginehost's revocation list")
    print("plugins/revocations.jws: sequence " + str(payload.get("sequence")) + ", verified to the Enginehost signing root")


# --- announcements -------------------------------------------------------------


def repository_from_issue(body):
    """The `Repository` field of the registration issue form."""
    match = re.search(r"###\s*Repository\s*\n+\s*(\S+)", body or "")
    if not match:
        return None
    value = match.group(1).strip().strip("`")
    value = re.sub(r"^https://github\.com/", "", value, flags=re.IGNORECASE).rstrip("/")
    return value if REPO_NAME.match(value) else None


def announcement(third_party):
    """What the triggering event asks for: (repo or None, report text or None, act).

    Read from GITHUB_EVENT_PATH, never from the workflow's `${{ }}`
    expressions, so nothing a sender wrote is ever interpolated into a shell.
    A dispatch is a hint and always leads to a full run.  A registration issue
    is acted on only when its author is the GitHub account the list names for
    that repository's maintainer; anyone else's issue gets an answer and
    changes nothing.
    """
    name = os.environ.get("GITHUB_EVENT_NAME", "")
    path = os.environ.get("GITHUB_EVENT_PATH", "")
    if not path or not os.path.isfile(path):
        return None, None, True
    event = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    if name == "repository_dispatch":
        repo = str((event.get("client_payload") or {}).get("repo", ""))
        if not REPO_NAME.match(repo):
            log("The dispatch names no repository; rebuilding everything.")
            return None, None, True
        log("Announced by dispatch: " + repo)
        return repo, None, True
    if name == "issues":
        issue = event.get("issue") or {}
        author = str((issue.get("user") or {}).get("login", ""))
        repo = repository_from_issue(issue.get("body"))
        if repo is None:
            return None, "The form's Repository field must be `owner/name`; nothing was done.", False
        listed = third_party.get(repo.lower())
        if listed is None:
            return None, (
                "`" + repo + "` is not in `plugins/third-party.json`, so it cannot register. A maintainer is "
                "listed by a pull request to that file; see `plugins/README.md`."
            ), False
        if author.lower() != listed[0]["github"].lower():
            return None, (
                "Only @" + listed[0]["github"] + ", the maintainer the list names for `" + repo + "`, "
                "can ask for it to be registered. Nothing was done."
            ), False
        log("Registration requested by @" + author + " for " + repo)
        return repo, None, True
    return None, None, True


# --- the whole index -----------------------------------------------------------


def generate(existing_text, announced=None):
    """(index document, registrations document, report lines)."""
    registrations_document = json.loads(ORIGINS_PATH.read_text(encoding="utf-8"))
    registered = registrations_document["origins"]
    third_party, _ = load_third_party()
    previous = previous_envelopes(existing_text)
    report = []

    # Everything that may belong in the index: what is registered, every
    # listed third-party repository (a registration they publish is picked up
    # here, on schedule, without anyone sending anything), and whatever the
    # event announced.
    candidates = [entry["repo"] for entry in registered]
    known = {repo.lower() for repo in candidates}
    for repo, (_, _, written) in third_party.items():
        if repo not in known:
            candidates.append(written)
            known.add(repo)
    if announced and announced.lower() not in known:
        if owner_of(announced) == OFFICIAL_OWNER:
            candidates.append(announced)
        else:
            report.append(announced + " is neither Droidtop's nor listed as third party; ignored.")

    pins = {entry["repo"].lower(): entry for entry in registered}
    history_document = load_history()
    history = history_document["keys"]
    entries = []
    kept = []
    for repo in candidates:
        was = pins.get(repo.lower())
        listed = third_party.get(repo.lower())
        try:
            if owner_of(repo) == OFFICIAL_OWNER:
                pin = None
                if was is not None:
                    pin = dict(was)
                    pin["key"] = recorded_key(history, repo, was["keySha256"])
                entry, record, change, refused = index_for(
                    repo, "official", pin, None, previous.get(repo.lower(), {})
                )
            elif listed is not None:
                maintainer, keys, _ = listed
                # The registration is re-read on every run: withdrawing it, or
                # the list dropping the key it was signed with, takes the
                # repository out of the index.
                key = registration_of(repo, maintainer, keys)
                pinned = (was or {}).get("keySha256")
                if pinned and pinned.upper() != key.sha256 and pinned.upper() in keys:
                    # A third party's key changes only by an edit to
                    # third-party.json: while the registered key is still
                    # listed, a registration naming another key is refused.
                    raise KeptRegistration(
                        repo + " registered with key " + key.sha256 + " while its registered key " + pinned
                        + " is still listed; a third party's key changes only when third-party.json drops the old one"
                    )
                entry, record, change, refused = index_for(
                    repo, "third-party", {"keySha256": key.sha256}, maintainer, previous.get(repo.lower(), {})
                )
                record["maintainer"] = maintainer["id"]
                if pinned is None:
                    change = "registered"
                elif pinned.upper() != key.sha256:
                    change = "rotated"
            else:
                # Registered once as third party, since delisted.
                report.append(repo + " is no longer in plugins/third-party.json; deregistered.")
                continue
        except Rejected as reason:
            if was is None:
                if repo.lower() == (announced or "").lower() or owner_of(repo) == OFFICIAL_OWNER:
                    report.append("Not registered: " + str(reason))
                continue
            if listed is not None and not isinstance(reason, KeptRegistration):
                # A third party that withdrew its registration, or whose list
                # entry no longer names the key it signed with, is out.
                report.append("Deregistered: " + str(reason))
                continue
            # An official repository that stops validating keeps its
            # registration, so the pin survives, and is left out of this
            # index: devices then ask GitHub for it directly and verify it
            # themselves, rather than being told it has published nothing.
            warn(str(reason))
            report.append("Registered but not valid now: " + str(reason))
            kept.append(was)
            continue
        for line in refused:
            warn(repo + " " + line)
        if not entry["releases"] and was is None:
            report.append("Not registered: " + repo + " has no release that validates.")
            continue
        # Every key a repository is indexed under is on record, with the
        # certified document for an official one; a repository registered
        # before the history existed gets its first line the same way.
        if change is None and recorded_key(history, repo, record["keySha256"]) is None:
            change = "registered"
        if change is not None:
            history.append({
                "repo": repo,
                "trust": entry["trust"],
                "keySha256": record["keySha256"],
                "serial": record.get("keySerial", 0),
                "replaces": (was or {}).get("keySha256") if change == "rotated" else None,
                "acceptedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "key": entry["key"],
            })
            report.append(
                ("Registered " if change == "registered" else "Rotated ") + repo + " (" + entry["trust"]
                + ", key " + record["keySha256"] + ", serial " + str(record.get("keySerial", 0)) + ")."
            )
        kept.append(record)
        entries.append(entry)

    registrations_document = dict(registrations_document)
    registrations_document["origins"] = kept
    index = {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "origins": entries,
    }
    return index, registrations_document, report, history_document


def dump(document):
    """The repository's one JSON style: indent 1, real UTF-8, trailing newline."""
    return json.dumps(document, indent=1, ensure_ascii=False) + "\n"


def body_changed(fresh, existing_text):
    if existing_text is None:
        return True
    try:
        existing = json.loads(existing_text)
    except ValueError:
        return True
    without = dict(existing)
    stamp = without.pop("generatedAt", None)
    compare = dict(fresh)
    compare.pop("generatedAt", None)
    if json.dumps(without, sort_keys=True) != json.dumps(compare, sort_keys=True):
        return True
    # Same content: rewrite only when the timestamp is old enough that
    # enginehost would soon stop trusting it.
    if not stamp:
        return True
    try:
        made = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return True
    return datetime.now(timezone.utc) - made > REFRESH_AFTER


def check(existing):
    """What a push can check without spending API calls: the files agree and parse."""
    if existing is None:
        sys.exit("plugins/index.json is missing; run generator/plugins_index.py")
    global OFFICIAL_ROOT
    OFFICIAL_ROOT = official_root()
    check_revocations()
    third_party, _ = load_third_party()
    check_history(json.loads(ORIGINS_PATH.read_text(encoding="utf-8"))["origins"], OFFICIAL_ROOT)
    document = json.loads(existing)
    if document.get("schemaVersion") != SCHEMA_VERSION:
        sys.exit("plugins/index.json: unexpected schemaVersion")
    registered = json.loads(ORIGINS_PATH.read_text(encoding="utf-8"))["origins"]
    for entry in registered:
        repo = entry["repo"]
        if not REPO_NAME.match(repo):
            sys.exit("plugins/origins.json: " + repr(repo) + " is not owner/name")
        maintainer = entry.get("maintainer")
        if owner_of(repo) == OFFICIAL_OWNER:
            if maintainer is not None:
                sys.exit("plugins/origins.json: " + repo + " is Droidtop's and cannot have a maintainer")
        elif maintainer is None or third_party.get(repo.lower(), ({},))[0].get("id") != maintainer:
            sys.exit("plugins/origins.json: " + repo + " is not listed for maintainer " + repr(maintainer))
    listed = {entry["repo"] for entry in document["origins"]}
    expected = {entry["repo"] for entry in registered}
    if listed - expected:
        sys.exit("plugins/index.json names unregistered repositories: " + str(sorted(listed - expected)))
    if expected - listed:
        # Allowed: a registered repository that does not validate on a run is
        # left out, and devices take the GitHub API path for it.
        print("Registered but not in the index (not valid on the last run): " + str(sorted(expected - listed)))
    for entry in document["origins"]:
        if entry.get("trust") not in ("official", "third-party"):
            sys.exit("plugins/index.json: " + entry["repo"] + " has no trust level")
        if (entry["trust"] == "third-party") != (owner_of(entry["repo"]) != OFFICIAL_OWNER):
            sys.exit("plugins/index.json: " + entry["repo"] + " has the wrong trust level")
    check_envelope_packs(json.loads(existing))
    print("plugins/index.json, origins.json, third-party.json and the envelope packs are consistent")


# The official root key, read once by main().
OFFICIAL_ROOT = None


def main():
    global OFFICIAL_ROOT, JWS, SIGNING_ROOT
    JWS, SIGNING_ROOT = v1_tooling()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="validate the committed files instead of writing")
    parser.add_argument("--event", action="store_true", help="also act on what the triggering GitHub event announces")
    parser.add_argument("--report", type=pathlib.Path, help="write what this run registered or refused here (Markdown)")
    args = parser.parse_args()

    existing = INDEX_PATH.read_text(encoding="utf-8") if INDEX_PATH.is_file() else None
    try:
        if args.check:
            check(existing)
            return
        OFFICIAL_ROOT = official_root()
        announced, answer, act = announcement(load_third_party()[0]) if args.event else (None, None, True)
        if not act:
            log(answer)
            if args.report:
                args.report.write_text(answer + "\n", encoding="utf-8")
            return
        index, registrations, report, history = generate(existing, announced)
    except Rejected as reason:
        sys.exit(str(reason))
    except urllib.error.HTTPError as error:
        sys.exit("GitHub answered HTTP " + str(error.code) + " while listing releases")
    for line in report:
        log(line)
    if args.report:
        args.report.write_text(
            ("\n".join("- " + line for line in report) if report else "- Nothing new to register.") + "\n",
            encoding="utf-8",
        )
    history_text = dump(history)
    if not HISTORY_PATH.is_file() or history_text != HISTORY_PATH.read_text(encoding="utf-8"):
        HISTORY_PATH.write_text(history_text, encoding="utf-8")
        log("plugins/key-history.json written: " + str(len(history["keys"])) + " keys on record")
    registrations_text = dump(registrations)
    if registrations_text != ORIGINS_PATH.read_text(encoding="utf-8"):
        ORIGINS_PATH.write_text(registrations_text, encoding="utf-8")
        log("plugins/origins.json written: " + str(len(registrations["origins"])) + " registered repositories")
    write_envelope_packs(index)
    if not body_changed(index, existing):
        log("plugins/index.json is already current")
        return
    PLUGINS_DIR.mkdir(exist_ok=True)
    INDEX_PATH.write_text(dump(index), encoding="utf-8")
    log("plugins/index.json written: " + str(sum(len(e["releases"]) for e in index["origins"])) + " releases")


if __name__ == "__main__":
    main()
