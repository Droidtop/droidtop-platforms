"""Who may register a repository: the third-party list, a repository's signed registration, and the key history."""

import json
import re
import sys

from common import Rejected
from crypto import verifies
from fetch import repository_file
from keys import Key, b64, certificate_serial, key_document, normalize_origin, origin_of, owner_of, registration_statement
from layout import ALGORITHM, HISTORY_COMMENT, HISTORY_PATH, MAINTAINER_ID, OFFICIAL_OWNER, REGISTRATION, REPO_NAME, RESERVED_WORDS, THIRD_PARTY_PATH




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


def check_history(registered, root):
    """What makes the key history an audit trail rather than a note. [root] is the Enginehost root's key document and key (keys.official_root()).

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
            serial = certificate_serial(document, root)
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
