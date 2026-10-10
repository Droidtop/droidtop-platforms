#!/usr/bin/env python3
"""Generate droidtop-plugins/index.json: every official droidtop plugin that has a signed release.

droidtop (the app) reads this ONE file from raw.githubusercontent.com as its official
plugin catalog (Droidtop/droidtop docs/SPEC.md 12a "The catalog"): Plugins > Add >
Catalogs > droidtop. The file is droidtop's plugin catalog index, schema version 1, the
same format gamegrab-sources/catalog publishes minus its `catalog` and `disclaimer`
blocks (the official catalog has neither).

What enters the index: every *.droidplugin.tar.xz asset of every release of every public,
unarchived repository of the Droidtop organisation whose name starts with
`droidtop-plugin-`, provided the bundle
  * carries origin.cert, a plugin certificate issued by droidtop's plugin master
    (droidtop-plugins/master-key.json, the key pinned in the app as MasterKey) that
    covers the manifest's plugin id and is valid now, and
  * its manifest.sig verifies against the key that certificate certifies, and
  * its manifest names origin `droidtop` and an id under `droidtop.`.
A prerelease is the "testing" stream, anything else "stable". droidtop offers only the
stable stream; the others are listed so a later build can opt in.

Nothing a repository says is trusted for more than display: the app verifies each bundle's
signature and every payload hash again on the device. This script refuses what the app
would refuse, so the index does not offer it. It is the sibling of plugins_index.py (the
Enginehost index) and runs in the same workflow (.github/workflows/plugins-index.yml).

  droidtop_plugins_index.py --build   rebuild droidtop-plugins/index.json from the repositories
  droidtop_plugins_index.py --check   validate the committed files, no network

Signatures are checked with the openssl command line, which every GitHub runner has.
GH_TOKEN, when set, raises the API allowance.
"""

import argparse
import base64
import hashlib
import io
import json
import os
import pathlib
import re
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
DIR = ROOT / "droidtop-plugins"
INDEX = DIR / "index.json"
MASTER_KEY = DIR / "master-key.json"

SCHEMA_VERSION = 1
ALGORITHM = "SHA256withECDSA"
ORGANISATION = "Droidtop"
REPO_PREFIX = "droidtop-plugin-"
ORIGIN = "droidtop"
CERT_FILE = "origin.cert"
CERT_PREFIX = "droidtop-plugin-cert-v1"
BUNDLE_SUFFIX = ".droidplugin.tar.xz"
MAX_BUNDLES_PER_RELEASE = 8
MAX_BUNDLE_BYTES = 512 * 1024 * 1024
# Per plugin and stream: a plugin's newest stable release must never fall off the list
# because a busy branch published many pre-releases after it.
KEEP_RELEASES = {"stable": 5, "testing": 3}
RETRIES = 3
RETRY_PAUSE_SECONDS = 10
USER_AGENT = "droidtop-platforms-droidtop-plugins-index"
HEX_64 = re.compile(r"[0-9a-f]{64}")


class Rejected(Exception):
    """A repository, release or bundle the index leaves out, with the reason."""


def log(message):
    print(message, flush=True)


def warn(message):
    print("::warning::" + message, flush=True)


# --- GitHub --------------------------------------------------------------------


def with_retries(fetch):
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


def request(url, api):
    req = urllib.request.Request(url)
    req.add_header("User-Agent", USER_AGENT)
    if api:
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("X-GitHub-Api-Version", "2022-11-28")
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token and url.startswith("https://api.github.com/"):
        req.add_header("Authorization", "Bearer " + token)
    return req


def api(url):
    def once():
        with urllib.request.urlopen(request(url, True), timeout=60) as response:
            return json.loads(response.read().decode("utf-8")), response.headers.get("Link")
    return with_retries(once)


def download(url, limit):
    def once():
        with urllib.request.urlopen(request(url, False), timeout=300) as response:
            data = response.read(limit + 1)
            if len(data) > limit:
                raise Rejected(url + " is larger than " + str(limit) + " bytes")
            return data
    return with_retries(once)


def next_link(link):
    if not link:
        return None
    for part in link.split(","):
        segments = part.split(";")
        if any(s.strip() == 'rel="next"' for s in segments[1:]):
            return segments[0].strip().strip("<>")
    return None


def paged(url):
    while url:
        page, link = api(url)
        yield from page
        url = next_link(link)


def repositories():
    for repo in paged("https://api.github.com/orgs/" + ORGANISATION + "/repos?type=public&per_page=100"):
        if repo["name"].startswith(REPO_PREFIX) and not repo.get("archived") and not repo.get("private") and not repo.get("fork"):
            yield repo


# --- keys and signatures -------------------------------------------------------


def openssl(*arguments):
    return subprocess.run(["openssl", *arguments], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)


def sha256_hex(data):
    return hashlib.sha256(data).hexdigest()


def p256_der(spki_b64, what):
    try:
        der = base64.b64decode(spki_b64, validate=True)
    except (ValueError, TypeError):
        raise Rejected(what + ": the key is not base64")
    with tempfile.NamedTemporaryFile(suffix=".der") as key:
        key.write(der)
        key.flush()
        result = openssl("pkey", "-pubin", "-inform", "DER", "-in", key.name, "-noout", "-text")
    text = result.stdout.decode(errors="replace")
    if result.returncode != 0 or not ("prime256v1" in text or "P-256" in text):
        raise Rejected(what + ": not an EC P-256 SubjectPublicKeyInfo")
    return der


def verifies(message, signature_b64, der):
    try:
        signature = base64.b64decode(signature_b64.strip(), validate=True)
    except (ValueError, TypeError):
        return False
    with tempfile.TemporaryDirectory() as temporary:
        folder = pathlib.Path(temporary)
        (folder / "message").write_bytes(message)
        (folder / "signature").write_bytes(signature)
        (folder / "key.der").write_bytes(der)
        result = openssl("dgst", "-sha256", "-verify", str(folder / "key.der"), "-keyform", "DER",
                         "-signature", str(folder / "signature"), str(folder / "message"))
    return result.returncode == 0


def load_master():
    """droidtop's plugin master (public): (der, key block). The same key the app pins as MasterKey."""
    document = json.loads(MASTER_KEY.read_text(encoding="utf-8"))
    der = p256_der(document.get("publicKeySpki", ""), "master-key.json")
    if str(document.get("keySha256", "")).lower() != sha256_hex(der):
        raise SystemExit("master-key.json: keySha256 is not the key's")
    return der, {
        "formatVersion": 1,
        "algorithm": ALGORITHM,
        "origin": ORIGIN,
        "publicKeySpki": base64.b64encode(der).decode("ascii"),
        "keySha256": sha256_hex(der),
    }


# --- bundles -------------------------------------------------------------------


def manifest_of(bundle, what):
    """manifest.json bytes, manifest.sig text and origin.cert text (or None) from a .droidplugin.tar.xz."""
    wanted = ("manifest.json", "manifest.sig", CERT_FILE)
    try:
        with tarfile.open(fileobj=io.BytesIO(bundle), mode="r:xz") as archive:
            found = {}
            for member in archive:
                if member.name in wanted and member.isfile() and member.size <= 1024 * 1024:
                    found[member.name] = archive.extractfile(member).read()
    except (tarfile.TarError, EOFError, OSError) as error:
        raise Rejected(what + ": not a readable tar.xz (" + str(error) + ")")
    if "manifest.json" not in found or "manifest.sig" not in found:
        raise Rejected(what + ": no manifest.json and manifest.sig at the top of the bundle")
    cert = found.get(CERT_FILE)
    return found["manifest.json"], found["manifest.sig"].decode("ascii", "replace"), cert.decode("utf-8", "replace") if cert else None


def cert_signed_bytes(cert_id, plugin_ids, spki_b64, not_before, not_after):
    """What the plugin master signs (the app's PluginCertificates.signedBytes)."""
    return (CERT_PREFIX + "\n" + "id:" + cert_id + "\n" + "plugins:" + ",".join(plugin_ids) + "\n"
            + "key:" + spki_b64 + "\n" + "notBefore:" + str(not_before) + "\n" + "notAfter:" + str(not_after) + "\n").encode("utf-8")


def covers(plugin_ids, plugin_id):
    for entry in plugin_ids:
        if entry.endswith(".*"):
            prefix = entry[:-1]
            if plugin_id.startswith(prefix) and len(plugin_id) > len(prefix):
                return True
        elif entry == plugin_id:
            return True
    return False


def certified_key(cert_text, master_der, plugin_id, what):
    """The repository key origin.cert certifies for plugin_id under droidtop's master, checked as the app checks it."""
    try:
        cert = json.loads(cert_text)
        cert_id, plugin_ids = cert["certId"], list(cert["pluginIds"])
        spki, not_before, not_after = cert["publicKeySpki"].strip(), int(cert["notBefore"]), int(cert["notAfter"])
        issuer = cert["issuer"]
    except (ValueError, KeyError, TypeError):
        raise Rejected(what + ": " + CERT_FILE + " is not a plugin certificate")
    if cert.get("formatVersion") != 1 or str(issuer.get("keySha256", "")).lower() != sha256_hex(master_der):
        raise Rejected(what + ": " + CERT_FILE + " was not issued by droidtop's master")
    if not verifies(cert_signed_bytes(cert_id, plugin_ids, spki, not_before, not_after), str(issuer.get("signature", "")), master_der):
        raise Rejected(what + ": the master's signature on " + CERT_FILE + " does not verify")
    der = p256_der(spki, what + " certified key")
    if str(cert.get("keySha256", "")).lower() != sha256_hex(der):
        raise Rejected(what + ": the certificate's keySha256 is not its key's")
    if not covers(plugin_ids, plugin_id):
        raise Rejected(what + ": the certificate is for " + ", ".join(plugin_ids) + ", not " + plugin_id)
    if not not_before <= int(time.time()) <= not_after:
        raise Rejected(what + ": the certificate " + cert_id + " is not valid now")
    return der


def release_entry(release, asset, bundle, master_der):
    what = release["tag_name"] + "/" + asset["name"]
    manifest_bytes, signature, cert = manifest_of(bundle, what)
    try:
        manifest = json.loads(manifest_bytes)
    except ValueError:
        raise Rejected(what + ": manifest.json is not JSON")
    plugin_id = str(manifest.get("id", ""))
    if cert is None:
        raise Rejected(what + ": no " + CERT_FILE + "; the official catalog lists certified bundles only")
    if not verifies(manifest_bytes, signature, certified_key(cert, master_der, plugin_id, what)):
        raise Rejected(what + ": manifest.sig does not verify against the certified key")
    if manifest.get("origin") != ORIGIN or plugin_id != plugin_id.lower() or not plugin_id.startswith(ORIGIN + "."):
        raise Rejected(what + ": the manifest's origin and id are not under origin " + repr(ORIGIN))
    label = str(manifest.get("label") or "").strip()
    version = str(manifest.get("version") or "").strip()
    if not label or not version:
        raise Rejected(what + ": the manifest has no label or version")
    description = manifest.get("description")
    return plugin_id, label, description if isinstance(description, str) and description.strip() else None, {
        "version": version,
        "stream": "testing" if release.get("prerelease") else "stable",
        "publishedAt": release.get("published_at"),
        "manifestSha256": sha256_hex(manifest_bytes),
        "bundle": {
            "name": asset["name"],
            "url": asset["browser_download_url"],
            "size": len(bundle),
            "sha256": sha256_hex(bundle),
        },
    }


def known_entries(previous):
    """Releases already in the committed index, by bundle URL, size and publish time: they are not downloaded again."""
    known = {}
    for origin in (previous or {}).get("origins", []):
        for plugin in origin.get("plugins", []):
            for release in plugin.get("releases", []):
                bundle = release.get("bundle", {})
                known[(bundle.get("url"), bundle.get("size"), release.get("publishedAt"))] = (plugin, release)
    return known


# --- the index -----------------------------------------------------------------


def build(previous):
    master_der, key_block = load_master()
    master_sha = key_block["keySha256"]
    known = known_entries(previous)
    previous_master = ((previous or {}).get("origins") or [{}])[0].get("key", {}).get("keySha256")
    plugins = {}
    plugin_owner = {}
    refused = []
    for repo in sorted(repositories(), key=lambda r: r["full_name"].lower()):
        name = repo["full_name"]
        for release in paged("https://api.github.com/repos/" + name + "/releases?per_page=100"):
            if release.get("draft"):
                continue
            assets = [a for a in release.get("assets", []) if a["name"].endswith(BUNDLE_SUFFIX)]
            for asset in assets[:MAX_BUNDLES_PER_RELEASE]:
                what = name + " " + release["tag_name"] + "/" + asset["name"]
                try:
                    if asset["size"] > MAX_BUNDLE_BYTES:
                        raise Rejected(what + ": larger than " + str(MAX_BUNDLE_BYTES) + " bytes")
                    cached = known.get((asset["browser_download_url"], asset["size"], release.get("published_at")))
                    # A bundle verified against the same master is not downloaded again; the app re-verifies
                    # every bundle on the device, so a stale entry can make the catalog late, never lie.
                    if cached and previous_master == master_sha:
                        plugin, listed = cached
                        plugin_id, label, description = plugin["id"], plugin["label"], plugin.get("description")
                        release_json = dict(listed, stream="testing" if release.get("prerelease") else "stable")
                    else:
                        log("downloading " + what)
                        bundle = download(asset["browser_download_url"], MAX_BUNDLE_BYTES)
                        plugin_id, label, description, release_json = release_entry(release, asset, bundle, master_der)
                    owner = plugin_owner.setdefault(plugin_id, name)
                    if owner != name:
                        raise Rejected(what + ": plugin " + plugin_id + " is already listed from " + owner)
                    entry = plugins.setdefault(plugin_id, {"id": plugin_id, "releases": []})
                    entry["releases"].append((release.get("published_at") or "", label, description, release_json))
                except Rejected as reason:
                    refused.append(str(reason))
    listed = []
    for plugin_id in sorted(plugins):
        ordered = sorted(plugins[plugin_id]["releases"], key=lambda r: r[0], reverse=True)
        kept, counts = [], {}
        for item in ordered:
            stream = item[3]["stream"]
            if counts.get(stream, 0) < KEEP_RELEASES.get(stream, 3):
                counts[stream] = counts.get(stream, 0) + 1
                kept.append(item)
        # Label and description come from the newest release's signed manifest.
        listed.append({"id": plugin_id, "label": ordered[0][1], "description": ordered[0][2], "releases": [r[3] for r in kept]})
    document = {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": None,
        "origins": [{"origin": ORIGIN, "trust": "official", "key": key_block, "plugins": listed}] if listed else [],
    }
    return document, refused


def body(document):
    return {k: v for k, v in document.items() if k != "generatedAt"}


def dump(document):
    return json.dumps(document, indent=1, ensure_ascii=False) + "\n"


def check_document(document):
    """What the app's parser requires, and that the key block is droidtop's master. Returns a list of problems."""
    problems = []
    if document.get("schemaVersion") != SCHEMA_VERSION:
        problems.append("schemaVersion is not " + str(SCHEMA_VERSION))
    if "catalog" in document or "disclaimer" in document:
        problems.append("the official catalog has no catalog or disclaimer block")
    master = load_master()[1]["keySha256"]
    seen = set()
    for origin in document.get("origins", []):
        if origin.get("origin") != ORIGIN or origin.get("trust") != "official":
            problems.append("origin " + repr(origin.get("origin")) + " is not the official origin")
        key = origin.get("key", {})
        if key.get("origin") != ORIGIN or key.get("algorithm") != ALGORITHM or key.get("keySha256") != master:
            problems.append("the key block is not droidtop's master")
        for plugin in origin.get("plugins", []):
            plugin_id = plugin.get("id", "")
            if not plugin_id.startswith(ORIGIN + ".") or plugin_id != plugin_id.lower() or plugin_id in seen:
                problems.append("plugin " + repr(plugin_id) + " is not unique under its origin")
            seen.add(plugin_id)
            if not plugin.get("label") or not plugin.get("releases"):
                problems.append("plugin " + repr(plugin_id) + " has no label or no release")
            for release in plugin.get("releases", []):
                bundle = release.get("bundle", {})
                if release.get("stream") not in ("stable", "testing", "unstable") \
                        or not HEX_64.fullmatch(str(release.get("manifestSha256", ""))) \
                        or not HEX_64.fullmatch(str(bundle.get("sha256", ""))) \
                        or not str(bundle.get("url", "")).startswith("https://"):
                    problems.append("plugin " + repr(plugin_id) + " has a malformed release")
    return problems


def summary(document, refused):
    lines = ["## droidtop plugin index", ""]
    for origin in document["origins"]:
        for plugin in origin["plugins"]:
            lines.append("- " + plugin["id"] + ": " + ", ".join(r["version"] + " (" + r["stream"] + ")" for r in plugin["releases"]))
    if not document["origins"]:
        lines.append("- nothing is published yet")
    if refused:
        lines += ["", "### Left out", ""] + ["- " + r for r in refused]
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    log("\n".join(lines))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--build", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args()
    previous = json.loads(INDEX.read_text(encoding="utf-8")) if INDEX.is_file() else None
    if args.check:
        problems = check_document(previous) if previous is not None else ["droidtop-plugins/index.json does not exist"]
        for problem in problems:
            print("::error::" + problem, flush=True)
        if problems:
            sys.exit(1)
        log("droidtop-plugins/index.json agrees with master-key.json")
        return
    document, refused = build(previous)
    for reason in refused:
        warn(reason)
    problems = check_document(document)
    if problems:
        for problem in problems:
            print("::error::" + problem, flush=True)
        sys.exit(1)
    if previous is not None and body(previous) == body(document):
        document["generatedAt"] = previous.get("generatedAt")
    else:
        document["generatedAt"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    INDEX.write_text(dump(document), encoding="utf-8")
    summary(document, refused)


if __name__ == "__main__":
    main()
