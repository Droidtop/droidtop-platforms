"""The one Python verifier of droidtop's JWS signatures: Enginehost's scripts/bundle_jws.py.

droidtop's signatures (a JWS with an x5c chain to a pinned root key; docs/SPEC.md 12a in droidtop, Droidtop/tracker#550) are
verified in Kotlin by droidtop-shared's ChainSignature, and in Python by Enginehost's bundle_jws.py, which mirrors it (chain,
revocation-free profile, EKU per purpose, P-256 keys) and is what Enginehost's own CI signs and checks bundles with. Both
index generators use that one, loaded from the checkout the workflow pins (ENGINEHOST_TOOLING); there is no third copy.
"""

import os
import pathlib
import sys


def bundle_jws(required):
    """Enginehost's bundle_jws module, or None when ENGINEHOST_TOOLING is unset and the caller can go without it."""
    tooling = os.environ.get("ENGINEHOST_TOOLING")
    if not tooling:
        if required:
            raise SystemExit("ENGINEHOST_TOOLING must name a checkout of Droidtop/enginehost (its scripts/bundle_jws.py verifies the signatures)")
        return None
    scripts = str(pathlib.Path(tooling) / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    import bundle_jws as module  # noqa: E402 -- Enginehost's own verifier, pinned by the workflow
    return module
