"""The org rename (Droidtop -> mytop-project, 2026-11-23): identities stay, locations move."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from keys import identity_repo, location_of, normalize_origin, origin_of, owner_of  # noqa: E402
from layout import OFFICIAL_OWNER  # noqa: E402


class OrgRenameTest(unittest.TestCase):
    def test_a_name_in_the_new_org_is_its_registered_identity(self):
        self.assertEqual("Droidtop/enginehost-renpy-plugin", identity_repo("mytop-project/enginehost-renpy-plugin"))
        self.assertEqual("Droidtop/enginehost-renpy-plugin", identity_repo("Mytop-Project/enginehost-renpy-plugin"))
        self.assertEqual("someone/plugin", identity_repo("someone/plugin"))

    def test_the_identity_is_what_signatures_name(self):
        repo = identity_repo("mytop-project/enginehost-renpy-plugin")
        self.assertEqual(OFFICIAL_OWNER, owner_of(repo))
        self.assertEqual(normalize_origin("https://github.com/Droidtop/enginehost-renpy-plugin"), origin_of(repo))

    def test_an_official_repository_is_fetched_from_the_new_org(self):
        self.assertEqual("mytop-project/enginehost-renpy-plugin", location_of("Droidtop/enginehost-renpy-plugin"))
        self.assertEqual("someone/plugin", location_of("someone/plugin"))


if __name__ == "__main__":
    unittest.main()
