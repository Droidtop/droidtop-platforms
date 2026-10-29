"""droidtop_plugins_index verifies a plugin manifest with Enginehost's bundle_jws, not a verifier of its own.

Needs ENGINEHOST_TOOLING (a checkout of Droidtop/enginehost with scripts/) and the openssl command line; skipped without them.
Run: python3 -m unittest discover -s generator -p 'test_*.py'
"""
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jws as jws_tooling  # noqa: E402
from common import Rejected  # noqa: E402

TOOLING = os.environ.get("ENGINEHOST_TOOLING")
ARC = "2.25.230248497294207031301727532441854392946"
MANIFEST = b'{"id":"droidtop.demo","origin":"droidtop","version":"1.0.0","label":"Demo"}'


def openssl(*args):
    subprocess.run(["openssl", *args], check=True, capture_output=True)


@unittest.skipUnless(TOOLING and pathlib.Path(TOOLING, "scripts", "bundle_jws.py").is_file(), "ENGINEHOST_TOOLING is not set")
class Verification(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import droidtop_plugins_index as index
        cls.index = index
        cls.bundle = jws_tooling.bundle_jws(required=True)
        cls.dir = pathlib.Path(tempfile.mkdtemp())
        cls.root = cls.key("root")
        cls.other_root = cls.key("other")
        cls.root_spki = cls.bundle.private_key_spki(cls.root)

    @classmethod
    def key(cls, name):
        path = cls.dir / (name + ".key")
        openssl("ecparam", "-name", "prime256v1", "-genkey", "-noout", "-out", str(path))
        return path

    @classmethod
    def leaf(cls, name, signer, uris, eku=ARC + ".1"):
        key = cls.key(name)
        csr, cert, ext = (cls.dir / (name + suffix) for suffix in (".csr", ".crt", ".ext"))
        ext.write_text("basicConstraints=CA:FALSE\nkeyUsage=digitalSignature\nextendedKeyUsage=" + eku + "\nsubjectAltName=" + ",".join("URI:" + u for u in uris) + "\n")
        openssl("req", "-new", "-key", str(key), "-subj", "/CN=" + name, "-out", str(csr))
        openssl("x509", "-req", "-in", str(csr), "-CAkey", str(signer), "-CA", str(cls.self_signed(signer)), "-CAcreateserial",
                "-extfile", str(ext), "-days", "30", "-outform", "DER", "-out", str(cert))
        return key, cert.read_bytes()

    @classmethod
    def self_signed(cls, signer):
        cert = signer.with_suffix(".ca.pem")
        if not cert.exists():
            openssl("req", "-new", "-x509", "-key", str(signer), "-subj", "/CN=" + signer.stem, "-days", "30", "-out", str(cert))
        return cert

    def signed(self, signer, uris, content=MANIFEST, eku=ARC + ".1"):
        key, cert = self.leaf("leaf%d" % len(list(self.dir.iterdir())), signer, uris, eku)
        return self.bundle.sign(content, key, [cert], "plugin", detached=True)

    def verify(self, jws, content=MANIFEST):
        return self.index.signed_plugin_ids("demo", content, jws, self.root_spki)

    def test_a_manifest_signed_for_droidtop_verifies_and_names_its_plugins(self):
        jws = self.signed(self.root, ["urn:droidtop:origin:droidtop", "urn:droidtop:plugin:droidtop.demo"])
        self.assertEqual(["droidtop.demo"], self.verify(jws))

    def test_a_changed_manifest_does_not_verify(self):
        jws = self.signed(self.root, ["urn:droidtop:origin:droidtop"])
        with self.assertRaises(Rejected):
            self.verify(jws, MANIFEST.replace(b"1.0.0", b"9.9.9"))

    def test_a_certificate_for_another_origin_is_refused(self):
        with self.assertRaises(Rejected):
            self.verify(self.signed(self.root, ["urn:droidtop:origin:acme"]))

    def test_a_chain_to_another_root_is_refused(self):
        with self.assertRaises(Rejected):
            self.verify(self.signed(self.other_root, ["urn:droidtop:origin:droidtop"]))

    def test_a_certificate_for_another_purpose_is_refused(self):
        with self.assertRaises(Rejected):
            self.verify(self.signed(self.root, ["urn:droidtop:origin:droidtop"], eku=ARC + ".2"))


if __name__ == "__main__":
    unittest.main()
