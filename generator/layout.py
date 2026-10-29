"""Where the plugins index lives and the names, limits and rules it is built on (generator/plugins_index.py)."""

from datetime import timedelta
import pathlib
import re



ROOT = pathlib.Path(__file__).resolve().parent.parent
PLUGINS_DIR = ROOT / "plugins"
INDEX_PATH = PLUGINS_DIR / "index.json"
ORIGINS_PATH = PLUGINS_DIR / "origins.json"
THIRD_PARTY_PATH = PLUGINS_DIR / "third-party.json"
ROOT_KEY_PATH = PLUGINS_DIR / "official-root-key.json"
HISTORY_PATH = PLUGINS_DIR / "key-history.json"
# One file per repository holding every release envelope the index lists for
# it, keyed by the envelope's sha256 (see write_envelope_packs).
PACKS_DIR = PLUGINS_DIR / "envelopes"
HISTORY_COMMENT = (
    "Every signing key the index has accepted for a repository, in order: its first registration and each "
    "rotation, with the key document (for an official repository, with the root's certificate and serial). "
    "Written by generator/plugins_index.py and never edited by hand; --check re-verifies every certificate "
    "and that serials only rise."
)
SCHEMA_VERSION = 1
RELEASE_ENVELOPE = "enginehost-release.json"
# A runtime component's release (Droidtop/enginehost docs/engine-bundle-format.md,
# "Component bundles") names its envelope differently, so an Enginehost from
# before components skips it; Enginehost reads both, and so does this index.
COMPONENT_ENVELOPE = "enginehost-component.json"
RELEASE_ENVELOPES = (RELEASE_ENVELOPE, COMPONENT_ENVELOPE)
KEY_DOCUMENT = "enginehost-public-key.json"
SIGNING_CERTIFICATE = "enginehost-signing-certificate.pem"
REVOCATIONS_PATH = PLUGINS_DIR / "revocations.jws"
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
# Directly in any lib/<abi>/, or anywhere under the payload's top-level
# lib/<abi>/ (a component keeps one build per engine series in
# lib/<abi>/<series>/), which is the rule Enginehost's installer applies.
NATIVE_LIBRARY = re.compile(r"(?:^|/)lib/([^/]+)/[^/]+\.so$|^lib/([^/]+)/.+\.so$")
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

# What a download of this index is allowed to be: the release envelopes, key documents, certificates and the small assets
# hashed here are kilobytes; anything past this is not one of them.
MAX_DOWNLOAD_BYTES = 8 * 1024 * 1024
