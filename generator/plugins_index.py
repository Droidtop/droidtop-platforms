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
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
PLUGINS_DIR = ROOT / "plugins"
INDEX_PATH = PLUGINS_DIR / "index.json"
ORIGINS_PATH = PLUGINS_DIR / "origins.json"
THIRD_PARTY_PATH = PLUGINS_DIR / "third-party.json"
ROOT_KEY_PATH = PLUGINS_DIR / "official-root-key.json"
HISTORY_PATH = PLUGINS_DIR / "key-history.json"
HISTORY_COMMENT = (
    "Every signing key the index has accepted for a repository, in order: its first registration and each "
    "rotation, with the key document (for an official repository, with the root's certificate and serial). "
    "Written by generator/plugins_index.py and never edited by hand; --check re-verifies every certificate "
    "and that serials only rise."
)
SCHEMA_VERSION = 1
RELEASE_ENVELOPE = "enginehost-release.json"
KEY_DOCUMENT = "enginehost-public-key.json"
REGISTRATION = "enginehost-registration.json"
REGISTRATION_STATEMENT = "enginehost-registration-v1"
ALGORITHM = "SHA256withECDSA"
# What a replacement key's certificate signs before its identity (enginehost
# scripts/certify-repository-key.py; a first key's certificate has no prefix).
CERTIFICATE_V2 = "enginehost-origin-key-v2"

# The organisation whose repositories are official.  Official is never a
# claim: it is a key the Enginehost root certified for that exact origin.
OFFICIAL_OWNER = "droidtop"
# Official bundles' ID namespace.  A third-party build in it could present
# itself as, or sit beside, an update to an official bundle.
OFFICIAL_BUNDLE_PREFIX = "dev.enginehost."
# Words a third-party maintainer's id or name may not contain.
RESERVED_WORDS = ("droidtop", "enginehost")
# A bundle that carries native libraries carries at least these
# (Droidtop/enginehost docs/engine-bundle-format.md).
REQUIRED_ABIS = ("arm64-v8a", "x86_64")
NATIVE_LIBRARY = re.compile(r"(?:^|/)lib/([^/]+)/[^/]+\.so$")
# Where a repository keeps its key document and registration.  These are
# forks of the engines they wrap, so the default branch is usually upstream's
# own; the plugin branch is looked at first, as enginehost does.
REPOSITORY_FILE_BRANCHES = ("plugin-core", "main", "master", "HEAD")
REPO_NAME = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
MAINTAINER_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,38}$")

# An asset with no digest of GitHub's own is hashed here, but only when it is
# small enough that downloading it to hash it is not absurd.  The one asset
# that always matters -- the release envelope -- is a few kilobytes, and it is
# the one enginehost verifies before believing anything in it.
HASH_IF_SMALLER_THAN = 2 * 1024 * 1024

# How old the committed index may be before it is rewritten even though
# nothing changed.  Keeps `generatedAt` honest (enginehost stops trusting a
# stale index) without a commit per scheduled run.
REFRESH_AFTER = timedelta(hours=20)

# Server errors are retried this many times in all, with a growing pause.
RETRIES = 4
RETRY_PAUSE_SECONDS = 10


class Rejected(Exception):
    """A repository or release that does not validate; the message says why."""


class KeptRegistration(Rejected):
    """Not indexed this run, but the registration and its pin stand."""


def log(message):
    print(message, flush=True)


def warn(message):
    # A GitHub annotation, so a refused official release is visible on the run.
    print("::warning::" + message, flush=True)


def with_retries(fetch):
    """Runs fetch(), again after a pause when GitHub answers with a server error.

    A single HTTP 500 while listing one repository failed the whole scheduled
    run of 2026-09-25 05:06, so the index stayed six hours behind the builds
    published that morning and Enginehost's catalog did not offer them.
    """
    for attempt in range(RETRIES):
        try:
            return fetch()
        except urllib.error.HTTPError as error:
            if error.code < 500 or attempt == RETRIES - 1:
                raise
        except urllib.error.URLError:
            if attempt == RETRIES - 1:
                raise
        time.sleep(RETRY_PAUSE_SECONDS * (attempt + 1))


def api(url):
    return with_retries(lambda: api_once(url))


def api_once(url):
    request = urllib.request.Request(url)
    request.add_header("Accept", "application/vnd.github+json")
    request.add_header("X-GitHub-Api-Version", "2022-11-28")
    request.add_header("User-Agent", "droidtop-platforms-plugins-index")
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        request.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8")), response.headers.get("Link")


def next_link(link):
    if not link:
        return None
    for part in link.split(","):
        segments = part.split(";")
        if any(s.strip() == 'rel="next"' for s in segments[1:]):
            return segments[0].strip().strip("<>")
    return None


def releases(repo):
    url = "https://api.github.com/repos/" + repo + "/releases?per_page=100"
    while url:
        page, link = api(url)
        for release in page:
            if not release.get("draft"):
                yield release
        url = next_link(link)


def download(url):
    return with_retries(lambda: download_once(url))


def download_once(url):
    request = urllib.request.Request(url)
    request.add_header("User-Agent", "droidtop-platforms-plugins-index")
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token and not url.startswith("https://raw.githubusercontent.com/"):
        request.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def repository_file(repo, name):
    """A file from the repository's tree, from raw.githubusercontent.com (no API allowance)."""
    for branch in REPOSITORY_FILE_BRANCHES:
        try:
            return download("https://raw.githubusercontent.com/" + repo + "/" + branch + "/" + name)
        except urllib.error.HTTPError as error:
            if error.code != 404:
                raise
    return None


def sha256_hex(data):
    return hashlib.sha256(data).hexdigest().upper()


def origin_of(repo):
    return "https://github.com/" + repo.lower()


def normalize_origin(value):
    candidate = value.strip().rstrip("/")
    if candidate.endswith(".git"):
        candidate = candidate[:-4]
    match = re.fullmatch(r"https://github\.com/([^/]+)/([^/]+)", candidate, re.IGNORECASE)
    if not match:
        raise Rejected("not a GitHub repository origin: " + value)
    return "https://github.com/" + match.group(1).lower() + "/" + match.group(2).lower()


def owner_of(repo):
    return repo.split("/", 1)[0].lower()


# --- signatures ---------------------------------------------------------------


def openssl(*arguments, data=None):
    return subprocess.run(
        ["openssl", *arguments], input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False
    )


def is_p256(spki_der):
    with tempfile.NamedTemporaryFile(suffix=".der") as key:
        key.write(spki_der)
        key.flush()
        result = openssl("pkey", "-pubin", "-inform", "DER", "-in", key.name, "-noout", "-text")
    text = result.stdout.decode(errors="replace")
    return result.returncode == 0 and ("prime256v1" in text or "P-256" in text)


def verifies(message, signature_der, spki_der):
    """SHA256withECDSA, the way enginehost's java.security.Signature checks it."""
    with tempfile.TemporaryDirectory() as temporary:
        folder = pathlib.Path(temporary)
        (folder / "message").write_bytes(message)
        (folder / "signature").write_bytes(signature_der)
        (folder / "key.der").write_bytes(spki_der)
        result = openssl(
            "dgst", "-sha256", "-verify", str(folder / "key.der"), "-keyform", "DER",
            "-signature", str(folder / "signature"), str(folder / "message"),
        )
    return result.returncode == 0


def b64(value, what):
    try:
        return base64.b64decode(value, validate=True)
    except (ValueError, TypeError):
        raise Rejected(what + " is not valid base64")


class Key:
    """One ECDSA P-256 public key: its DER SubjectPublicKeyInfo and fingerprint."""

    def __init__(self, spki_b64, declared_sha256, what):
        if not isinstance(spki_b64, str) or not isinstance(declared_sha256, str):
            raise Rejected(what + ": publicKeySpki and keySha256 are required")
        self.spki_b64 = spki_b64
        self.der = b64(spki_b64, what + " publicKeySpki")
        self.sha256 = sha256_hex(self.der)
        if declared_sha256.upper() != self.sha256:
            raise Rejected(what + ": keySha256 does not match the key")
        if not is_p256(self.der):
            raise Rejected(what + ": not an ECDSA P-256 key")


def key_document(raw, expected_origin, what):
    """A repository's enginehost-public-key.json, checked the way enginehost checks it."""
    try:
        document = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise Rejected(what + " is not JSON")
    if document.get("formatVersion", 1) != 1 or document.get("algorithm") != ALGORITHM:
        raise Rejected(what + ": unsupported format or algorithm")
    if normalize_origin(document.get("origin", "")) != expected_origin:
        raise Rejected(what + " declares another origin")
    return document, Key(document.get("publicKeySpki"), document.get("keySha256"), what)


def official_root():
    document = json.loads(ROOT_KEY_PATH.read_text(encoding="utf-8"))
    if document.get("formatVersion") != 1 or document.get("algorithm") != ALGORITHM:
        raise Rejected("plugins/official-root-key.json: unsupported format")
    return document, Key(document.get("publicKeySpki"), document.get("keySha256"), "official root key")


def certificate_serial(document, root):
    """The serial the Enginehost root certified this key for this origin with, or None.

    The same check as enginehost's OriginKeyDocuments.parseCertified: serial 0
    is the original certificate format; a replacement key's certificate signs
    its serial too (`enginehost-origin-key-v2`), so only the root can raise it.
    """
    root_document, root_key = root
    issuer = document.get("issuer")
    if not isinstance(issuer, dict):
        return None
    if issuer.get("id") != root_document.get("id") or issuer.get("algorithm") != ALGORITHM:
        return None
    if str(issuer.get("keySha256", "")).upper() != root_key.sha256:
        return None
    serial = issuer.get("serial", 0)
    if not isinstance(serial, int) or isinstance(serial, bool) or serial < 0:
        return None
    identity = (
        normalize_origin(document["origin"]) + "\n"
        + document["algorithm"] + "\n"
        + document["publicKeySpki"] + "\n"
        + document["keySha256"].upper() + "\n"
    )
    if serial:
        identity = CERTIFICATE_V2 + "\n" + identity + str(serial) + "\n"
    try:
        signature = b64(issuer.get("signature", ""), "issuer signature")
    except Rejected:
        return None
    return serial if verifies(identity.encode("utf-8"), signature, root_key.der) else None


# --- the third-party list ------------------------------------------------------


def load_third_party():
    """plugins/third-party.json, validated: {repo (lowercase): (maintainer, {fingerprint: Key}, repo as written)}."""
    if not THIRD_PARTY_PATH.is_file():
        return {}, []
    document = json.loads(THIRD_PARTY_PATH.read_text(encoding="utf-8"))
    maintainers = document.get("maintainers")
    if not isinstance(maintainers, list):
        raise Rejected("plugins/third-party.json: `maintainers` must be a list")
    by_repo = {}
    seen_ids = set()
    for entry in maintainers:
        ident = entry.get("id", "")
        what = "plugins/third-party.json maintainer " + repr(ident)
        if not MAINTAINER_ID.match(ident) or ident in seen_ids:
            raise Rejected(what + ": id must be unique, lowercase letters, digits and dashes")
        seen_ids.add(ident)
        name = entry.get("name")
        github = entry.get("github")
        if not isinstance(name, str) or not name.strip():
            raise Rejected(what + ": `name` is required")
        if not isinstance(github, str) or not re.fullmatch(r"[A-Za-z0-9-]+", github):
            raise Rejected(what + ": `github` must be the maintainer's GitHub login")
        for word in RESERVED_WORDS:
            if word in ident or word in name.lower():
                raise Rejected(what + ": may not name itself " + word)
        keys = {}
        for raw in entry.get("keys") or []:
            if raw.get("algorithm") != ALGORITHM:
                raise Rejected(what + ": keys must be " + ALGORITHM)
            key = Key(raw.get("publicKeySpki"), raw.get("keySha256"), what + " key")
            keys[key.sha256] = key
        if not keys:
            raise Rejected(what + ": lists no key")
        repos = entry.get("repos")
        if not isinstance(repos, list) or not repos:
            raise Rejected(what + ": lists no repository")
        for repo in repos:
            if not isinstance(repo, str) or not REPO_NAME.match(repo):
                raise Rejected(what + ": " + repr(repo) + " is not owner/name")
            if owner_of(repo) == OFFICIAL_OWNER:
                raise Rejected(what + ": " + repo + " belongs to Droidtop and is official, not third party")
            if repo.lower() in by_repo:
                raise Rejected(what + ": " + repo + " is listed twice")
            by_repo[repo.lower()] = ({"id": ident, "name": name.strip(), "github": github}, keys, repo)
    return by_repo, maintainers


def registration_of(repo, maintainer, keys):
    """The key a third-party repository registered itself with, from its signed enginehost-registration.json."""
    raw = repository_file(repo, REGISTRATION)
    if raw is None:
        raise Rejected(repo + " publishes no " + REGISTRATION)
    try:
        document = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise Rejected(repo + ": " + REGISTRATION + " is not JSON")
    origin = origin_of(repo)
    if document.get("formatVersion") != 1:
        raise Rejected(repo + ": unsupported " + REGISTRATION)
    if normalize_origin(document.get("origin", "")) != origin:
        raise Rejected(repo + ": " + REGISTRATION + " names another repository")
    if document.get("maintainer") != maintainer["id"]:
        raise Rejected(repo + ": " + REGISTRATION + " names another maintainer")
    fingerprint = str(document.get("keySha256", "")).upper()
    key = keys.get(fingerprint)
    if key is None:
        raise Rejected(repo + ": registered with a key the list does not name for " + maintainer["id"])
    statement = registration_statement(origin, maintainer["id"], fingerprint)
    if not verifies(statement, b64(document.get("signatureBase64", ""), "registration signature"), key.der):
        raise Rejected(repo + ": the registration's signature does not verify")
    return key


def registration_statement(origin, maintainer, fingerprint):
    return (REGISTRATION_STATEMENT + "\n" + origin + "\n" + maintainer + "\n" + fingerprint + "\n").encode("utf-8")


# --- one repository ------------------------------------------------------------


def digest_of(asset, body=None):
    """GitHub's own digest where it has one; otherwise our own, for small assets."""
    declared = asset.get("digest") or ""
    if declared.startswith("sha256:"):
        return declared.split(":", 1)[1].lower()
    if body is None:
        if asset.get("size", 0) > HASH_IF_SMALLER_THAN:
            # Nothing is lost: the bundle carries its own signature inside and
            # is verified file by file at install time regardless.
            return None
        body = download(asset["browser_download_url"])
    return hashlib.sha256(body).hexdigest()


def stream_of(release, envelope):
    """The stream is the release envelope's own channel; the flag is the fallback."""
    channel = envelope.get("channel")
    if channel in ("stable", "testing", "unstable"):
        return channel
    return "testing" if release.get("prerelease") else "stable"


def abis_of(manifest):
    return {m.group(1) for f in manifest.get("files") or [] for m in [NATIVE_LIBRARY.search(f.get("path", ""))] if m}


def check_envelope(body, origin, key, assets, third_party, admitted_before):
    """Every bundle in one release envelope, verified; raises Rejected with the reason."""
    try:
        envelope = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        raise Rejected("the release envelope is not JSON")
    if envelope.get("formatVersion") != 1 or not isinstance(envelope.get("bundles"), list) or not envelope["bundles"]:
        raise Rejected("the release envelope has no bundles")
    names = {asset["name"] for asset in assets}
    for bundle in envelope["bundles"]:
        manifest_bytes = b64(bundle.get("manifestBase64", ""), "manifestBase64")
        signature = b64(bundle.get("signatureBase64", ""), "signatureBase64")
        try:
            manifest = json.loads(manifest_bytes)
        except (ValueError, UnicodeDecodeError):
            raise Rejected("a bundle manifest is not JSON")
        bundle_id = str(manifest.get("bundleId", "?"))
        signing = manifest.get("signing") or {}
        if normalize_origin(str(manifest.get("origin", ""))) != origin:
            raise Rejected(bundle_id + " names another origin")
        if signing.get("algorithm") != ALGORITHM or str(signing.get("keySha256", "")).upper() != key.sha256:
            raise Rejected(bundle_id + " is not signed by the key pinned for " + origin)
        if b64(signing.get("publicKeySpki", ""), "manifest publicKeySpki") != key.der:
            raise Rejected(bundle_id + " embeds a different public key")
        if not verifies(manifest_bytes, signature, key.der):
            raise Rejected(bundle_id + ": the manifest signature does not verify")
        if manifest.get("assetName") not in names:
            raise Rejected(bundle_id + ": the release is missing " + str(manifest.get("assetName")))
        if third_party and bundle_id.startswith(OFFICIAL_BUNDLE_PREFIX):
            raise Rejected(bundle_id + " is in the official " + OFFICIAL_BUNDLE_PREFIX + "* namespace")
        abis = abis_of(manifest)
        missing = [abi for abi in REQUIRED_ABIS if abi not in abis]
        if abis and missing and not admitted_before:
            raise Rejected(bundle_id + " carries native code without " + ", ".join(missing))
    return envelope


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
    entry["releases"] = []
    refused = []
    for release in listed:
        assets = release.get("assets") or []
        envelope_asset = next((a for a in assets if a["name"] == RELEASE_ENVELOPE), None)
        if envelope_asset is None:
            # A release with no envelope is not a plugin release; enginehost
            # skips it too.
            continue
        body = download(envelope_asset["browser_download_url"])
        body_sha = hashlib.sha256(body).hexdigest()
        try:
            envelope = check_envelope(
                body, origin, key, assets, third_party, previous.get(release["tag_name"]) == body_sha
            )
        except Rejected as reason:
            refused.append(release["tag_name"] + ": " + str(reason))
            continue
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


def previous_envelopes(existing_text):
    """{repo (lowercase): {tag: envelope sha256}} from the committed index."""
    try:
        document = json.loads(existing_text) if existing_text else {}
    except ValueError:
        return {}
    found = {}
    for entry in document.get("origins") or []:
        tags = {}
        for release in entry.get("releases") or []:
            for asset in release.get("assets") or []:
                if asset.get("name") == RELEASE_ENVELOPE and asset.get("sha256"):
                    tags[release["tag"]] = asset["sha256"].lower()
        found[entry.get("repo", "").lower()] = tags
    return found


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


def load_history():
    if not HISTORY_PATH.is_file():
        return {"comment": HISTORY_COMMENT, "keys": []}
    document = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
    if not isinstance(document.get("keys"), list):
        raise Rejected("plugins/key-history.json: `keys` must be a list")
    return document


def recorded_key(history, repo, fingerprint):
    """The key document key-history.json holds for this repository's [fingerprint], or None."""
    for line in reversed(history):
        if line.get("repo", "").lower() == repo.lower() and str(line.get("keySha256", "")).upper() == fingerprint.upper():
            return line.get("key")
    return None


def check_history(registered):
    """What makes the key history an audit trail rather than a note.

    Checked offline on every push: each official line's certificate verifies
    with the serial it records, serials only rise per repository, each line
    names the key it replaced, and every registration is pinned to the last
    key the history holds for it.
    """
    history = load_history()["keys"]
    last = {}
    for number, line in enumerate(history, 1):
        repo = line.get("repo", "")
        what = "plugins/key-history.json line " + str(number) + " (" + repo + ")"
        document = line.get("key")
        if not isinstance(document, dict):
            sys.exit(what + ": no key document")
        try:
            _, key = key_document(json.dumps(document).encode(), origin_of(repo), what)
        except Rejected as reason:
            sys.exit(str(reason))
        if key.sha256 != str(line.get("keySha256", "")).upper():
            sys.exit(what + ": keySha256 is not the document's key")
        previous = last.get(repo.lower())
        if line.get("trust") == "official":
            serial = certificate_serial(document, OFFICIAL_ROOT)
            if serial is None or serial != line.get("serial"):
                sys.exit(what + ": the root's certificate does not verify with serial " + str(line.get("serial")))
            if previous is not None and serial <= previous.get("serial", 0):
                sys.exit(what + ": serial " + str(serial) + " does not rise above " + str(previous.get("serial")))
        expected = previous.get("keySha256") if previous is not None else None
        if line.get("replaces") != expected:
            sys.exit(what + ": replaces " + str(line.get("replaces")) + ", not the key before it (" + str(expected) + ")")
        last[repo.lower()] = line
    for entry in registered:
        line = last.get(entry["repo"].lower())
        if line is not None and line["keySha256"].upper() != entry["keySha256"].upper():
            sys.exit("plugins/origins.json: " + entry["repo"] + " is pinned to a key the history does not end with")


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
    third_party, _ = load_third_party()
    check_history(json.loads(ORIGINS_PATH.read_text(encoding="utf-8"))["origins"])
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
    print("plugins/index.json, origins.json and third-party.json are consistent")


# The official root key, read once by main().
OFFICIAL_ROOT = None


def main():
    global OFFICIAL_ROOT
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
    if not body_changed(index, existing):
        log("plugins/index.json is already current")
        return
    PLUGINS_DIR.mkdir(exist_ok=True)
    INDEX_PATH.write_text(dump(index), encoding="utf-8")
    log("plugins/index.json written: " + str(sum(len(e["releases"]) for e in index["origins"])) + " releases")


if __name__ == "__main__":
    main()
