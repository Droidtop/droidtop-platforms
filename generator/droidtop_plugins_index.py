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
  * carries manifest.jws, a detached ES256 JWS over the exact manifest.json bytes with the
    repository's leaf certificate in x5c, issued by the droidtop root
    (droidtop-plugins/droidtop-root.pub, the key pinned in the app), and
  * the leaf is a plugin leaf (EKU .1, CA:FALSE, digitalSignature) naming
    urn:droidtop:origin:droidtop and, if it names plugins, the manifest's id, and
  * its manifest names origin `droidtop` and an id under `droidtop.`.
Expiry dates are not checked, as the app does not check them.
Each release is listed with its channel (`stream`; Droidtop/droidtop docs/SPEC.md 12a
"Channels"): a release is "stable"; a pre-release is "unstable" when it is one of the
per-push builds droidtop-plugin-bundle.yml publishes (tags `plugin-unstable*` and
`plugin-build*`), and "testing" otherwise. droidtop offers a channel's own line and every
steadier one. Each plugin carries the `category` of its newest release's manifest
(plugin-api.md 1.2 "Categories"), when it is one droidtop knows.

Nothing a repository says is trusted for more than display: the app verifies each bundle's
signature and every payload hash again on the device. This script refuses what the app
would refuse, so the index does not offer it. It is the sibling of plugins_index.py (the
Enginehost index) and runs in the same workflow (.github/workflows/plugins-index.yml).

  droidtop_plugins_index.py --build   rebuild droidtop-plugins/index.json from the repositories
  droidtop_plugins_index.py --check   validate the committed files, no network

Signatures are checked by Enginehost's scripts/bundle_jws.py (generator/jws.py, from the checkout ENGINEHOST_TOOLING names): the one
Python verifier of droidtop's chain signatures, which mirrors the app's.
GH_TOKEN, when set, raises the API allowance.
"""

import argparse
import base64
import io
import json
import os
import pathlib
import re
import sys
import tarfile
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import github  # noqa: E402
import jws as jws_tooling  # noqa: E402
from common import Rejected, log, sha256_hex, warn  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
DIR = ROOT / "droidtop-plugins"
INDEX = DIR / "index.json"
ROOT_KEY = DIR / "droidtop-root.pub"

SCHEMA_VERSION = 1
ALGORITHM = "droidtop-chain-v1"
ORGANISATION = "Droidtop"
REPO_PREFIX = "droidtop-plugin-"
ORIGIN = "droidtop"
ORIGIN_URN = "urn:droidtop:origin:"
PLUGIN_URN = "urn:droidtop:plugin:"
BUNDLE_SUFFIX = ".droidplugin.tar.xz"
MAX_BUNDLES_PER_RELEASE = 8
MAX_BUNDLE_BYTES = 512 * 1024 * 1024
# Per plugin and stream: a plugin's newest stable release must never fall off the list
# because a busy branch published many pre-releases after it.
KEEP_RELEASES = {"stable": 5, "testing": 3, "unstable": 3}
# The per-push pre-releases of droidtop-plugin-bundle.yml's unstable job (with the
# caller's optional release-tag-suffix).
UNSTABLE_TAG = re.compile(r"plugin-(unstable|build)([.-]|$)")
# droidtop's categories (plugin-api.md 1.2), and the 2026-10-15 ids droidtop reads as
# their successors; anything else is left out, which droidtop shows as "other".
CATEGORIES = {"sources", "emulators", "system", "sync", "integrations", "appearance", "other",
              "tools", "themes", "social", "games"}
GITHUB = github.Client("droidtop-platforms-droidtop-plugins-index")
HEX_64 = re.compile(r"[0-9a-f]{64}")


# --- GitHub --------------------------------------------------------------------


def paged(url):
    return GITHUB.paged(url)


def download(url, limit):
    return GITHUB.download(url, limit, timeout=300)


def repositories():
    for repo in paged("https://api.github.com/orgs/" + ORGANISATION + "/repos?type=public&per_page=100"):
        if repo["name"].startswith(REPO_PREFIX) and not repo.get("archived") and not repo.get("private") and not repo.get("fork"):
            yield repo


# --- keys and signatures -------------------------------------------------------


def load_root():
    """droidtop's root (public): (SubjectPublicKeyInfo DER, key block). The same key the app pins."""
    from cryptography.hazmat.primitives import serialization
    pem = ROOT_KEY.read_bytes()
    der = serialization.load_pem_public_key(pem).public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    return der, {
        "formatVersion": 1,
        "algorithm": ALGORITHM,
        "origin": ORIGIN,
        "publicKeySpki": base64.b64encode(der).decode("ascii"),
        "keySha256": sha256_hex(der),
    }


# --- bundles -------------------------------------------------------------------


def manifest_of(bundle, what):
    """manifest.json bytes and manifest.jws text from a .droidplugin.tar.xz."""
    wanted = ("manifest.json", "manifest.jws")
    try:
        with tarfile.open(fileobj=io.BytesIO(bundle), mode="r:xz") as archive:
            found = {}
            for member in archive:
                if member.name in wanted and member.isfile() and member.size <= 1024 * 1024:
                    found[member.name] = archive.extractfile(member).read()
    except (tarfile.TarError, EOFError, OSError) as error:
        raise Rejected(what + ": not a readable tar.xz (" + str(error) + ")")
    if "manifest.json" not in found or "manifest.jws" not in found:
        raise Rejected(what + ": no manifest.json and manifest.jws at the top of the bundle")
    return found["manifest.json"], found["manifest.jws"].decode("ascii", "replace")


def covers(plugin_ids, plugin_id):
    for entry in plugin_ids:
        if entry.endswith(".*"):
            prefix = entry[:-1]
            if plugin_id.startswith(prefix) and len(plugin_id) > len(prefix):
                return True
        elif entry == plugin_id:
            return True
    return False


def stream_of(release):
    """The channel a GitHub release is listed in."""
    if not release.get("prerelease"):
        return "stable"
    return "unstable" if UNSTABLE_TAG.match(str(release.get("tag_name", ""))) else "testing"


def category_of(manifest):
    """The manifest's category when droidtop knows it, else None."""
    category = manifest.get("category")
    return category if isinstance(category, str) and category in CATEGORIES else None


def signed_plugin_ids(what, manifest_bytes, jws, root_spki):
    """The plugin ids the manifest's signing certificate names (none: all of droidtop's), once manifest.jws verifies to the droidtop root for origin droidtop."""
    verifier = jws_tooling.bundle_jws(required=True)
    try:
        signed = verifier.verify(jws, "plugin", root_spki, manifest_bytes)
        if ORIGIN not in signed["origins"]:
            raise verifier.Refused("the signing certificate is not for origin " + ORIGIN)
        leaf = base64.b64decode(json.loads(verifier.b64url_decode(jws.split(".")[0]))["x5c"][0])
        names = verifier.uris(leaf)
    except (verifier.Refused, ValueError, KeyError, IndexError) as error:
        raise Rejected(what + ": manifest.jws does not verify to the droidtop root (" + str(error) + ")")
    return [u[len(PLUGIN_URN):] for u in names if u.startswith(PLUGIN_URN)]


def release_entry(release, asset, bundle, root_spki):
    what = release["tag_name"] + "/" + asset["name"]
    manifest_bytes, jws = manifest_of(bundle, what)
    try:
        manifest = json.loads(manifest_bytes)
    except ValueError:
        raise Rejected(what + ": manifest.json is not JSON")
    plugin_id = str(manifest.get("id", ""))
    named = signed_plugin_ids(what, manifest_bytes, jws, root_spki)
    if named and not covers(named, plugin_id):
        raise Rejected(what + ": the leaf is for " + ", ".join(named) + ", not " + plugin_id)
    if manifest.get("origin") != ORIGIN or plugin_id != plugin_id.lower() or not plugin_id.startswith(ORIGIN + "."):
        raise Rejected(what + ": the manifest's origin and id are not under origin " + repr(ORIGIN))
    label = str(manifest.get("label") or "").strip()
    version = str(manifest.get("version") or "").strip()
    if not label or not version:
        raise Rejected(what + ": the manifest has no label or version")
    description = manifest.get("description")
    if manifest.get("category") is not None and category_of(manifest) is None:
        warn(what + ": unknown category " + repr(manifest.get("category")) + "; listed without one")
    meta = (label, description if isinstance(description, str) and description.strip() else None,
            category_of(manifest))
    return plugin_id, meta, {
        "version": version,
        "stream": stream_of(release),
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
    root_spki, key_block = load_root()
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
                    # A bundle verified against the same root is not downloaded again; the app re-verifies
                    # every bundle on the device, so a stale entry can make the catalog late, never lie.
                    if cached and previous_master == master_sha:
                        plugin, listed = cached
                        plugin_id = plugin["id"]
                        meta = (plugin["label"], plugin.get("description"), plugin.get("category"))
                        release_json = dict(listed, stream=stream_of(release))
                    else:
                        log("downloading " + what)
                        bundle = download(asset["browser_download_url"], MAX_BUNDLE_BYTES)
                        plugin_id, meta, release_json = release_entry(release, asset, bundle, root_spki)
                    owner = plugin_owner.setdefault(plugin_id, name)
                    if owner != name:
                        raise Rejected(what + ": plugin " + plugin_id + " is already listed from " + owner)
                    entry = plugins.setdefault(plugin_id, {"id": plugin_id, "releases": []})
                    entry["releases"].append((release.get("published_at") or "", meta, release_json))
                except Rejected as reason:
                    refused.append(str(reason))
    listed = []
    for plugin_id in sorted(plugins):
        ordered = sorted(plugins[plugin_id]["releases"], key=lambda r: r[0], reverse=True)
        kept, counts = [], {}
        for item in ordered:
            stream = item[2]["stream"]
            if counts.get(stream, 0) < KEEP_RELEASES.get(stream, 3):
                counts[stream] = counts.get(stream, 0) + 1
                kept.append(item)
        # Label, description and category come from the newest release's signed manifest.
        label, description, category = ordered[0][1]
        plugin = {"id": plugin_id, "label": label, "description": description}
        if category is not None:
            plugin["category"] = category
        plugin["releases"] = [r[2] for r in kept]
        listed.append(plugin)
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
    """What the app's parser requires, and that the key block is droidtop's root. Returns a list of problems."""
    problems = []
    if document.get("schemaVersion") != SCHEMA_VERSION:
        problems.append("schemaVersion is not " + str(SCHEMA_VERSION))
    if "catalog" in document or "disclaimer" in document:
        problems.append("the official catalog has no catalog or disclaimer block")
    master = load_root()[1]["keySha256"]
    seen = set()
    for origin in document.get("origins", []):
        if origin.get("origin") != ORIGIN or origin.get("trust") != "official":
            problems.append("origin " + repr(origin.get("origin")) + " is not the official origin")
        key = origin.get("key", {})
        if key.get("origin") != ORIGIN or key.get("algorithm") != ALGORITHM or key.get("keySha256") != master:
            problems.append("the key block is not droidtop's root")
        for plugin in origin.get("plugins", []):
            plugin_id = plugin.get("id", "")
            if not plugin_id.startswith(ORIGIN + ".") or plugin_id != plugin_id.lower() or plugin_id in seen:
                problems.append("plugin " + repr(plugin_id) + " is not unique under its origin")
            seen.add(plugin_id)
            if not plugin.get("label") or not plugin.get("releases"):
                problems.append("plugin " + repr(plugin_id) + " has no label or no release")
            if "category" in plugin and plugin["category"] not in CATEGORIES:
                problems.append("plugin " + repr(plugin_id) + " has an unknown category")
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
        log("droidtop-plugins/index.json agrees with droidtop-root.pub")
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
