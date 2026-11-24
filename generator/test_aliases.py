"""Platform aliases: other names for one system, never shared between two systems (generator/build.py).

Run: python3 -m unittest discover -s generator -p 'test_*.py'
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build  # noqa: E402


def row(ident, name, **fields):
    return (ident, ident + ".json", "", dict({"id": ident, "name": name}, **fields))


class Aliases(unittest.TestCase):
    def test_an_alias_is_another_name_for_the_same_system(self):
        rows = [row("snes", "Nintendo SNES (Super Nintendo)", aliases=["Super Nintendo Entertainment System"])]
        self.assertEqual([], build.alias_problems(rows))

    def test_an_alias_that_is_another_systems_name_id_or_alias_is_refused(self):
        rows = [
            row("nes", "Nintendo Entertainment System", aliases=["Famicom Disk"]),
            row("snes", "Nintendo SNES", aliases=["nintendo-entertainment-system"]),
            row("fds", "Famicom Disk System", aliases=["Famicom  Disk"]),
        ]
        problems = build.alias_problems(rows)
        self.assertEqual(2, len(problems))
        self.assertIn("snes.json", problems[0])
        self.assertIn("fds.json", problems[1])

    def test_aliases_must_be_a_list_of_names(self):
        for bad in ("Linux", [""], [3], ["  "]):
            self.assertEqual(1, len(build.alias_problems([row("pc", "PC", aliases=bad)])))

    def test_the_names_in_the_tree_do_not_collide(self):
        self.assertEqual([], build.alias_problems(build.read_collection("platforms")[1]))


if __name__ == "__main__":
    unittest.main()
