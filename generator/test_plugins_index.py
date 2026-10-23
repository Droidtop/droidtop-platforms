"""The Enginehost plugins index's reading of bundle manifests and release envelopes.

Run: python3 -m unittest discover -s generator -p 'test_*.py'
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import plugins_index as index  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
