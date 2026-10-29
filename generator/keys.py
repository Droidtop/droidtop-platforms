"""Repository keys: a key and its fingerprint, the key document a repository publishes, and the root's certificate of an official key."""

import base64
import json
import re

from common import Rejected, sha256_hex
from crypto import is_p256, verifies
from layout import ALGORITHM, CERTIFICATE_V2, REGISTRATION_STATEMENT, ROOT_KEY_PATH




def fingerprint(data):
    """A key's fingerprint as the registry writes it: the SHA-256 of its DER, upper-case."""
    return sha256_hex(data).upper()


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
        self.sha256 = fingerprint(self.der)
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


def registration_statement(origin, maintainer, fingerprint):
    return (REGISTRATION_STATEMENT + "\n" + origin + "\n" + maintainer + "\n" + fingerprint + "\n").encode("utf-8")
