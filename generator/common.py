"""What the index generators share: the refusal they raise, how they report, and how they hash."""

import hashlib


class Rejected(Exception):
    """A repository, release, bundle or download the index leaves out; the message says why."""


def log(message):
    print(message, flush=True)


def warn(message):
    # A GitHub annotation, so a refused official release is visible on the run.
    print("::warning::" + message, flush=True)


def sha256_hex(data):
    """The digest as lower-case hex, the form the published indexes carry. A key fingerprint is upper-cased by the caller that publishes one."""
    return hashlib.sha256(data).hexdigest()
