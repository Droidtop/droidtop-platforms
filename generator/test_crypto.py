"""The ECDSA P-256 checks of the plugins index (generator/crypto.py), done with the cryptography package, not the openssl command line.

Run: python3 -m unittest discover -s generator -p 'test_*.py'
"""
import os
import sys
import unittest

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import crypto  # noqa: E402


def spki(key):
    return key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)


class Crypto(unittest.TestCase):
    p256 = ec.generate_private_key(ec.SECP256R1())

    def test_only_a_p256_key_is_p256(self):
        self.assertTrue(crypto.is_p256(spki(self.p256)))
        self.assertFalse(crypto.is_p256(spki(ec.generate_private_key(ec.SECP384R1()))))
        self.assertFalse(crypto.is_p256(spki(ec.generate_private_key(ec.SECP256K1()))))
        self.assertFalse(crypto.is_p256(spki(rsa.generate_private_key(65537, 2048))))
        self.assertFalse(crypto.is_p256(b"not a key"))

    def test_a_signature_verifies_for_its_message_and_key_only(self):
        message = b"manifest"
        signature = self.p256.sign(message, ec.ECDSA(hashes.SHA256()))
        self.assertTrue(crypto.verifies(message, signature, spki(self.p256)))
        self.assertFalse(crypto.verifies(b"changed", signature, spki(self.p256)))
        self.assertFalse(crypto.verifies(message, signature, spki(ec.generate_private_key(ec.SECP256R1()))))
        self.assertFalse(crypto.verifies(message, b"garbage", spki(self.p256)))
        self.assertFalse(crypto.verifies(message, signature, b"not a key"))


if __name__ == "__main__":
    unittest.main()
