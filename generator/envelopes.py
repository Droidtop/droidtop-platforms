"""Release envelopes: checking every bundle in one, and the per-repository packs the index names."""

import json
import sys

from common import Rejected, log, sha256_hex
from crypto import verifies
from fetch import download
from keys import b64, normalize_origin
from layout import ALGORITHM, HASH_IF_SMALLER_THAN, NATIVE_LIBRARY, OFFICIAL_BUNDLE_PREFIX, PACKS_DIR, PLUGINS_DIR, RELEASE_ENVELOPES, REQUIRED_ABIS




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
    return sha256_hex(body)


def stream_of(release, envelope):
    """The stream is the release envelope's own channel; the flag is the fallback."""
    channel = envelope.get("channel")
    if channel in ("stable", "testing", "unstable"):
        return channel
    return "testing" if release.get("prerelease") else "stable"


def abis_of(manifest):
    return {m.group(1) or m.group(2) for f in manifest.get("files") or []
            for m in [NATIVE_LIBRARY.search(f.get("path", ""))] if m}


def check_envelope(body, origin, key, assets, third_party, admitted_before, v1=(None, None)):
    """Every bundle in one release envelope, verified; raises Rejected with the reason.

    [v1] is (Enginehost's bundle_jws module, the Enginehost signing root's public key) when this run can check format v1, else (None, None).
    """
    jws, signing_root = v1
    try:
        envelope = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        raise Rejected("the release envelope is not JSON")
    if envelope.get("formatVersion") != 1 or not isinstance(envelope.get("bundles"), list) or not envelope["bundles"]:
        raise Rejected("the release envelope has no bundles")
    names = {asset["name"] for asset in assets}
    for bundle in envelope["bundles"]:
        manifest_bytes = b64(bundle.get("manifestBase64", ""), "manifestBase64")
        try:
            manifest = json.loads(manifest_bytes)
        except (ValueError, UnicodeDecodeError):
            raise Rejected("a bundle manifest is not JSON")
        bundle_id = str(manifest.get("bundleId", "?"))
        if normalize_origin(str(manifest.get("origin", ""))) != origin:
            raise Rejected(bundle_id + " names another origin")
        # Format v1, when this run can check it: the chain ends at the signing
        # root and its certificate names this origin. Only official repositories
        # are anchored at the root; a third party's v1 signature is the app's to check
        # against the key a person pinned, and here its legacy one is required.
        v1_verified = False
        if bundle.get("jws") and jws is not None and signing_root is not None and not third_party:
            try:
                named = jws.verify(bundle["jws"], "plugin", signing_root, manifest_bytes)
            except jws.Refused as reason:
                raise Rejected(bundle_id + ": its v1 signature does not verify: " + str(reason))
            if jws.origin_id(origin) not in named["origins"]:
                raise Rejected(bundle_id + ": its v1 signing certificate does not name " + origin)
            v1_verified = True
        if bundle.get("signatureBase64") or not v1_verified:
            signature = b64(bundle.get("signatureBase64", ""), "signatureBase64")
            signing = manifest.get("signing") or {}
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
                if asset.get("name") in RELEASE_ENVELOPES and asset.get("sha256"):
                    tags[release["tag"]] = asset["sha256"].lower()
        found[entry.get("repo", "").lower()] = tags
    return found


def pack_name(repo):
    return repo.lower().replace("/", "__") + ".json"


def write_envelope_packs(index):
    """
    One pack per repository: every envelope its index entry lists, keyed by
    sha256, so a device with none cached (a fresh install, cleared data)
    fetches one file per repository instead of one per release (Droidtop/
    tracker#550, 2026-10-24: 509 envelopes, one request each, on a reset
    console). Each envelope is the exact text the release published, so a
    device verifies it as it would one fetched alone. The entry names its
    pack by path and sha256; only a changed pack is rewritten, and a pack
    no entry names any more is removed.
    """
    PACKS_DIR.mkdir(parents=True, exist_ok=True)
    named = set()
    for entry in index["origins"]:
        pack = entry.pop("_pack", {})
        if not pack:
            continue
        name = pack_name(entry["repo"])
        text = json.dumps(
            {"schemaVersion": 1, "origin": entry["origin"], "envelopes": dict(sorted(pack.items()))},
            ensure_ascii=False,
            separators=(",", ":"),
        ) + "\n"
        data = text.encode("utf-8")
        path = PACKS_DIR / name
        if not path.is_file() or path.read_bytes() != data:
            path.write_bytes(data)
            log("plugins/envelopes/" + name + " written: " + str(len(pack)) + " envelopes, " + str(len(data)) + " bytes")
        entry["envelopePack"] = {"path": "envelopes/" + name, "sha256": sha256_hex(data), "size": len(data)}
        named.add(name)
    for stale in PACKS_DIR.glob("*.json"):
        if stale.name not in named:
            stale.unlink()
            log("plugins/envelopes/" + stale.name + " removed: no repository in the index names it")


def check_envelope_packs(index):
    """Each entry's pack exists, matches its hash, and holds every envelope the entry lists."""
    for entry in index["origins"]:
        pack = entry.get("envelopePack")
        if pack is None:
            continue
        path = PLUGINS_DIR / pack["path"]
        if not path.is_file():
            sys.exit("plugins/index.json: " + entry["repo"] + " names " + pack["path"] + ", which is missing")
        data = path.read_bytes()
        if sha256_hex(data) != pack["sha256"]:
            sys.exit("plugins/" + pack["path"] + " does not match the sha256 the index names")
        envelopes = json.loads(data)["envelopes"]
        for release in entry["releases"]:
            for asset in release["assets"]:
                if asset["name"] in RELEASE_ENVELOPES and asset["sha256"].lower() not in envelopes:
                    sys.exit("plugins/" + pack["path"] + " lacks the envelope of " + release["tag"])
