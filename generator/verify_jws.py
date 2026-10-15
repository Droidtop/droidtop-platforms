#!/usr/bin/env python3
"""Verifies a detached droidtop JWS (see sign_jws.py) against a root public key (droidtop root for official, gamegrab root for gamegrab).
Usage: verify_jws.py <typ> <content file> <jws file> <root.pub> [required SAN URN ...]
Checks: ES256 over the exact content bytes with the x5c leaf's key; the leaf is signed by Core's key
(ECDSA or RSA), CA:FALSE, digitalSignature, carries the EKU for the typ, and names each given URN.
Expiry is not checked (droidtop ignores it). Exits non-zero on any failure."""
import base64, sys
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding, utils

EKU_BASE = "2.25.230248497294207031301727532441854392946"
EKU = {"droidtop-plugin+jws": EKU_BASE + ".1", "droidtop-catalog+jws": EKU_BASE + ".2"}

def b64d(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))

def verify(typ, content, jws, core_pem, urns=()):
    import json
    h, mid, sig = jws.strip().split(".")
    if mid:
        raise ValueError("payload is not detached")
    header = json.loads(b64d(h))
    if header.get("alg") != "ES256" or header.get("typ") != typ or "crit" in header:
        raise ValueError("bad header %r" % header)
    leaf = x509.load_der_x509_certificate(base64.b64decode(header["x5c"][0]))
    core = serialization.load_pem_public_key(core_pem)
    if isinstance(core, ec.EllipticCurvePublicKey):
        core.verify(leaf.signature, leaf.tbs_certificate_bytes, ec.ECDSA(leaf.signature_hash_algorithm))
    else:
        core.verify(leaf.signature, leaf.tbs_certificate_bytes, padding.PKCS1v15(), leaf.signature_hash_algorithm)
    bc = leaf.extensions.get_extension_for_class(x509.BasicConstraints).value
    ku = leaf.extensions.get_extension_for_class(x509.KeyUsage).value
    eku = [o.dotted_string for o in leaf.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value]
    san = leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.UniformResourceIdentifier)
    if bc.ca or not ku.digital_signature or ku.key_cert_sign or EKU[typ] not in eku:
        raise ValueError("leaf profile wrong")
    for u in urns:
        if u not in san:
            raise ValueError("leaf lacks %s (has %s)" % (u, san))
    raw = b64d(sig)
    if len(raw) != 64:
        raise ValueError("signature not raw R||S")
    signing_input = h.encode() + b"." + base64.urlsafe_b64encode(content).rstrip(b"=")
    leaf.public_key().verify(utils.encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big")),
                             signing_input, ec.ECDSA(hashes.SHA256()))
    return san

if __name__ == "__main__":
    typ, cpath, jpath, corepath, *urns = sys.argv[1:]
    san = verify(typ, open(cpath, "rb").read(), open(jpath).read(), open(corepath, "rb").read(), urns)
    print("OK", " ".join(san))
