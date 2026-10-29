"""The `install` object on a player row: what the generator accepts and refuses (docs/FORMAT.md, "Install sources").

Run: python3 -m unittest discover -s generator -p 'test_*.py'
"""
import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build  # noqa: E402

PKG = "org.example.player"
GOOD = {
    "v": 1,
    "sources": [
        {"kind": "play", "id": PKG, "official": True},
        {"kind": "fdroid", "id": PKG},
        {"kind": "github", "repo": "example/player", "asset": "^player-.*-arm64-v8a\\.apk$", "abis": ["arm64-v8a"], "official": True},
        {"kind": "gitlab", "repo": "group/sub/player", "asset": "\\.apk$", "abis": ["arm64-v8a", "x86_64"]},
        {"kind": "page", "url": "https://example.org/download"},
    ],
    "needs": ["core-a"],
    "source": "README.md 'Installation' section",
}


def problems(change=None):
    install = copy.deepcopy(GOOD)
    if change:
        change(install)
    return build.install_problems(install, PKG)


class Install(unittest.TestCase):
    def test_a_complete_object_is_accepted(self):
        self.assertEqual(problems(), [])

    def test_a_citation_is_required(self):
        self.assertTrue(problems(lambda i: i.pop("source")))
        self.assertTrue(problems(lambda i: i.update(source="  ")))

    def test_an_unknown_version_or_field_is_refused(self):
        self.assertTrue(problems(lambda i: i.update(v=2)))
        self.assertTrue(problems(lambda i: i.update(mirror="x")))
        self.assertTrue(problems(lambda i: i["sources"][0].update(price="free")))

    def test_no_sources_means_leave_install_out(self):
        self.assertTrue(problems(lambda i: i.update(sources=[])))

    def test_a_store_id_must_be_the_rows_package(self):
        self.assertTrue(problems(lambda i: i["sources"][0].update(id="org.other.app")))
        self.assertTrue(problems(lambda i: i["sources"][1].update(id="not a package")))

    def test_a_release_source_needs_a_real_pattern_and_abis(self):
        self.assertTrue(problems(lambda i: i["sources"][2].update(asset="(")))
        self.assertTrue(problems(lambda i: i["sources"][2].update(abis=[])))
        self.assertTrue(problems(lambda i: i["sources"][2].update(abis=["mips"])))
        self.assertTrue(problems(lambda i: i["sources"][3].pop("asset")))  # abis without an asset
        self.assertTrue(problems(lambda i: i["sources"][2].update(repo="a/b/c")))

    def test_a_release_source_may_name_only_the_repository(self):
        self.assertEqual(problems(lambda i: i["sources"].append({"kind": "github", "repo": "example/other"})), [])

    def test_a_page_must_be_https(self):
        self.assertTrue(problems(lambda i: i["sources"][4].update(url="http://example.org")))

    def test_the_same_source_twice_is_refused(self):
        self.assertTrue(problems(lambda i: i["sources"].append(dict(i["sources"][1]))))

    def test_channel_is_stable_or_nightly(self):
        self.assertEqual(problems(lambda i: i["sources"][2].update(channel="nightly")), [])
        self.assertTrue(problems(lambda i: i["sources"][2].update(channel="beta")))

    def test_validate_reaches_a_player_row(self):
        row = ("players/x.json", "players/x.json", "", {"id": "x", "systemId": "s", "label": "L", "pkg": PKG, "install": {"v": 1}})
        collections = {
            "engines": ([], [("e", "engines/e.json", "", {"detect": [{"all": []}]})]),
            "players": ({}, [row]),
            "platforms": ({}, []),
            "bios": ({}, []),
        }
        with self.assertRaises(SystemExit) as raised:
            build.validate(collections)
        self.assertIn("install", str(raised.exception))


class Runners(unittest.TestCase):
    CORES = {"Droidtop/enginehost-renpy-plugin"}

    def good(self):
        return {
            "v": 1,
            "enginehost": {
                "core": {"repo": "Droidtop/enginehost-renpy-plugin"},
                "install": {
                    "v": 1,
                    "sources": [{"kind": "github", "repo": "Droidtop/enginehost", "asset": "^enginehost-latest\\.apk$"}],
                    "source": "README.md Install",
                },
            },
            "source": "docs/contract.md Current core repositories",
        }

    def test_a_complete_row_is_accepted(self):
        self.assertEqual(build.runners_problems(self.good(), self.CORES), [])

    def test_a_core_must_be_registered(self):
        runners = self.good()
        runners["enginehost"]["core"]["repo"] = "Droidtop/enginehost-made-up-plugin"
        self.assertTrue(build.runners_problems(runners, self.CORES))

    def test_the_enginehost_install_is_required_and_checked(self):
        runners = self.good()
        del runners["enginehost"]["install"]
        self.assertTrue(build.runners_problems(runners, self.CORES))
        runners = self.good()
        runners["enginehost"]["install"]["sources"] = [{"kind": "play", "id": "org.other.app"}]
        self.assertTrue(build.runners_problems(runners, self.CORES))

    def test_a_citation_and_a_known_shape_are_required(self):
        runners = self.good()
        del runners["source"]
        self.assertTrue(build.runners_problems(runners, self.CORES))
        runners = self.good()
        runners["joiplay"] = {}
        self.assertTrue(build.runners_problems(runners, self.CORES))


if __name__ == "__main__":
    unittest.main()
