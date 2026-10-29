"""ECDSA P-256 checks for the plugins index, with the cryptography package."""

import cryptography.exceptions
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec


def is_p256(spki_der):
    """Whether [spki_der] (a DER SubjectPublicKeyInfo) is an ECDSA key on P-256."""
    try:
        key = serialization.load_der_public_key(spki_der)
    except ValueError:
        return False
    return isinstance(key, ec.EllipticCurvePublicKey) and isinstance(key.curve, ec.SECP256R1)


def verifies(message, signature_der, spki_der):
    """SHA256withECDSA, the way enginehost's java.security.Signature checks it: [signature_der] is the DER signature."""
    try:
        key = serialization.load_der_public_key(spki_der)
        if not isinstance(key, ec.EllipticCurvePublicKey):
            return False
        key.verify(signature_der, message, ec.ECDSA(hashes.SHA256()))
    except (ValueError, cryptography.exceptions.InvalidSignature):
        return False
    return True
