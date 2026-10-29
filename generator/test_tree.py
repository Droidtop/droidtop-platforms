"""Generated rows go into the tree, one file per id, never into the composed monoliths (generator/tree.py).

Run: python3 -m unittest discover -s generator -p 'test_*.py'
"""
import json
import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build  # noqa: E402
import from_batocera  # noqa: E402
import tree  # noqa: E402


class Tree(unittest.TestCase):
    def setUp(self):
        self.root = pathlib.Path(tempfile.mkdtemp())
        for collection, ids in (("players", ["a"]), ("bios", ["amiga", "zx"])):
            (self.root / collection).mkdir()
            (self.root / collection / "_order.json").write_text(build.dump({"order": ids}), encoding="utf-8")
        (self.root / "players" / "a.json").write_text(build.dump({"id": "a", "systemId": "s", "label": "A", "pkg": "p", "argumentsTemplate": "", "killPackageProcesses": False}), encoding="utf-8")
        for system in ("amiga", "zx"):
            (self.root / "bios" / (system + ".json")).write_text(build.dump({"systemId": system, "name": system, "files": []}), encoding="utf-8")
        patcher = mock.patch.object(tree, "ROOT", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_new_player_is_a_file_and_is_named_in_the_order(self):
        tree.write("players", {"id": "b", "systemId": "s", "label": "B", "pkg": "q", "argumentsTemplate": "", "killPackageProcesses": False})
        self.assertEqual(["a", "b"], tree.order("players"))
        self.assertEqual("B", json.loads((self.root / "players" / "b.json").read_text())["label"])
        self.assertEqual(["a", "b"], [row["id"] for row in tree.rows("players")])

    def test_writing_a_row_again_does_not_name_it_twice(self):
        row = {"id": "a", "systemId": "s", "label": "A2", "pkg": "p", "argumentsTemplate": "", "killPackageProcesses": False}
        tree.write("players", row)
        self.assertEqual(["a"], tree.order("players"))
        self.assertEqual("A2", tree.rows("players")[0]["label"])

    def test_bios_ids_stay_sorted_and_the_file_style_is_the_repositorys(self):
        tree.write("bios", {"systemId": "c64", "name": "C64", "files": []}, sort_order=True)
        self.assertEqual(["amiga", "c64", "zx"], tree.order("bios"))
        text = (self.root / "bios" / "c64.json").read_text()
        self.assertEqual(build.dump(json.loads(text)), text)


class Batocera(unittest.TestCase):
    def test_systems_become_rows_with_md5s_merged_and_empty_ones_left_out(self):
        systems = {
            "odyssey2": {"name": "Videopac", "biosFiles": [{"file": "bios/o2.bin", "md5": "aa"}, {"file": "bios/o2.bin", "md5": "bb"}, {"file": "bios/o2.bin", "md5": "-"}]},
            "nobios": {"name": "None", "biosFiles": []},
        }
        self.assertEqual({"videopac": {"name": "Videopac", "files": [{"file": "bios/o2.bin", "md5": ["aa", "bb"]}]}}, from_batocera.convert(systems))


if __name__ == "__main__":
    unittest.main()
