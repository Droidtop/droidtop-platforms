"""The droidtop plugin index's channel and category rules (docs: droidtop_plugins_index.py).

Run: python3 -m unittest discover -s generator -p 'test_*.py'
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import droidtop_plugins_index as index  # noqa: E402


class Channels(unittest.TestCase):
    def test_a_release_is_stable(self):
        self.assertEqual(index.stream_of({"tag_name": "plugin-v1.5.0", "prerelease": False}), "stable")

    def test_the_bundle_workflows_per_push_builds_are_unstable(self):
        for tag in ("plugin-unstable", "plugin-build.42", "plugin-unstable-arm", "plugin-build-arm.7"):
            self.assertEqual(index.stream_of({"tag_name": tag, "prerelease": True}), "unstable", tag)

    def test_any_other_pre_release_is_testing(self):
        for tag in ("plugin-v1.6.0-beta.1", "plugin-builder", "plugin-unstabled"):
            self.assertEqual(index.stream_of({"tag_name": tag, "prerelease": True}), "testing", tag)


class Categories(unittest.TestCase):
    def test_a_known_category_is_copied(self):
        for category in ("sources", "system", "appearance", "tools", "games"):
            self.assertEqual(index.category_of({"category": category}), category)

    def test_anything_else_is_left_out(self):
        for manifest in ({}, {"category": "Sources"}, {"category": "misc"}, {"category": 3}):
            self.assertIsNone(index.category_of(manifest), manifest)


class Check(unittest.TestCase):
    def document(self, plugin):
        root = index.load_root()[1]
        return {"schemaVersion": index.SCHEMA_VERSION, "origins": [
            {"origin": "droidtop", "trust": "official", "key": root, "plugins": [plugin]}]}

    def plugin(self, **extra):
        release = {"version": "1.0", "stream": "unstable", "manifestSha256": "0" * 64,
                   "bundle": {"url": "https://example.invalid/b", "sha256": "1" * 64}}
        return dict({"id": "droidtop.example", "label": "Example", "releases": [release]}, **extra)

    def test_unstable_releases_and_a_known_category_pass(self):
        self.assertEqual(index.check_document(self.document(self.plugin(category="sync"))), [])

    def test_an_unknown_category_is_a_problem(self):
        problems = index.check_document(self.document(self.plugin(category="misc")))
        self.assertTrue(any("category" in p for p in problems), problems)


if __name__ == "__main__":
    unittest.main()
