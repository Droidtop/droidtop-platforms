"""The Enginehost plugins index's reading of bundle manifests and release envelopes.

Run: python3 -m unittest discover -s generator -p 'test_*.py'
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import envelopes as index  # noqa: E402


def manifest(*paths):
    return {"files": [{"path": p} for p in paths]}


class Abis(unittest.TestCase):
    def test_an_engine_bundle_counts_libraries_in_lib_abi(self):
        self.assertEqual(index.abis_of(manifest("lib/arm64-v8a/libgodot_android.so",
                                                "lib/x86_64/libgodot_android.so", "runtime/godot.apk")),
                         {"arm64-v8a", "x86_64"})

    def test_a_component_counts_its_per_series_builds(self):
        # spine-godot: lib/<abi>/godot-<series>/libspine_godot.so
        self.assertEqual(index.abis_of(manifest("lib/arm64-v8a/godot-4.2/libspine_godot.so",
                                                "lib/x86_64/godot-4.6/libspine_godot.so",
                                                "godot-4.2/spine-godot.gdextension")),
                         {"arm64-v8a", "x86_64"})

    def test_a_component_missing_an_abi_is_seen_missing_it(self):
        abis = index.abis_of(manifest("lib/arm64-v8a/godot-4.2/libspine_godot.so"))
        self.assertEqual([a for a in index.REQUIRED_ABIS if a not in abis], ["x86_64"])

    def test_no_native_code_is_no_abi(self):
        self.assertEqual(index.abis_of(manifest("payload/game.js", "LICENSE.txt")), set())


class Envelopes(unittest.TestCase):
    def test_both_envelope_names_are_remembered_from_the_committed_index(self):
        committed = {"origins": [{"repo": "Droidtop/enginehost-godot-plugin", "releases": [
            {"tag": "godot-v45-v2-unstable",
             "assets": [{"name": "enginehost-release.json", "sha256": "AA"}]},
            {"tag": "godot-component-spine-godot-v42-unstable",
             "assets": [{"name": "enginehost-component.json", "sha256": "BB"}]},
        ]}]}
        found = index.previous_envelopes(json.dumps(committed))
        self.assertEqual(found["droidtop/enginehost-godot-plugin"],
                         {"godot-v45-v2-unstable": "aa", "godot-component-spine-godot-v42-unstable": "bb"})


class Packs(unittest.TestCase):
    """A fresh device reads one pack per repository instead of one envelope per release."""

    def setUp(self):
        import hashlib, pathlib, tempfile
        self.hashlib = hashlib
        self.folder = tempfile.TemporaryDirectory()
        root = pathlib.Path(self.folder.name)
        self.saved = (index.PLUGINS_DIR, index.PACKS_DIR)
        index.PLUGINS_DIR, index.PACKS_DIR = root, root / "envelopes"

    def tearDown(self):
        index.PLUGINS_DIR, index.PACKS_DIR = self.saved
        self.folder.cleanup()

    def entry(self, repo, bodies):
        shas = [self.hashlib.sha256(b.encode()).hexdigest() for b in bodies]
        return {
            "repo": repo,
            "origin": "https://github.com/" + repo.lower(),
            "releases": [{"tag": "t" + str(n), "assets": [{"name": "enginehost-release.json", "sha256": sha}]}
                         for n, sha in enumerate(shas)],
            "_pack": dict(zip(shas, bodies)),
        }

    def test_the_pack_holds_each_envelope_as_published_and_the_entry_names_it(self):
        bodies = ['{"formatVersion":1,"bundles":[1]}\n', '{"formatVersion":1,"bundles":[2]}']
        document = {"origins": [self.entry("Droidtop/enginehost-renpy-plugin", bodies)]}
        index.write_envelope_packs(document)
        entry = document["origins"][0]
        self.assertNotIn("_pack", entry)
        pack = entry["envelopePack"]
        data = (index.PLUGINS_DIR / pack["path"]).read_bytes()
        self.assertEqual(self.hashlib.sha256(data).hexdigest(), pack["sha256"])
        envelopes = json.loads(data)["envelopes"]
        for body in bodies:
            # The text a device hashes is byte for byte what the release published.
            self.assertEqual(envelopes[self.hashlib.sha256(body.encode()).hexdigest()], body)
        index.check_envelope_packs(document)

    def test_a_pack_no_repository_names_is_removed(self):
        index.PACKS_DIR.mkdir(parents=True)
        (index.PACKS_DIR / "droidtop__gone.json").write_text("{}")
        document = {"origins": [self.entry("Droidtop/enginehost-ags-plugin", ["{}"])]}
        index.write_envelope_packs(document)
        self.assertEqual(sorted(p.name for p in index.PACKS_DIR.iterdir()), ["droidtop__enginehost-ags-plugin.json"])

    def test_check_refuses_a_pack_missing_a_listed_envelope(self):
        document = {"origins": [self.entry("Droidtop/enginehost-ags-plugin", ["{}"])]}
        index.write_envelope_packs(document)
        document["origins"][0]["releases"].append(
            {"tag": "new", "assets": [{"name": "enginehost-release.json", "sha256": "00" * 32}]})
        with self.assertRaises(SystemExit):
            index.check_envelope_packs(document)


if __name__ == "__main__":
    unittest.main()
