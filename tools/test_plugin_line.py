"""compose writes the same tree whatever newline the platform's text mode uses.

On Windows, a subprocess given text input gets "\\n" written as "\\r\\n"; the
update-index paths then ended in "\\r" and plugin-core's files were not where
they belong. This test makes text-mode input do that here too, and composes a
line in a scratch repository.

Run: python3 -m unittest discover -s tools -p 'test_*.py'
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import plugin_line  # noqa: E402

REAL_RUN = subprocess.run


def windows_text_mode(args, **kw):
    """subprocess.run as Windows does it: text-mode input gets CRLF."""
    if (kw.get("text") or kw.get("universal_newlines")) and isinstance(kw.get("input"), str):
        kw["input"] = kw["input"].replace("\n", "\r\n")
    return REAL_RUN(args, **kw)


def run(*args, input=None):
    return REAL_RUN(["git", *args], check=True, capture_output=True, input=input).stdout.decode()


def commit(files, message):
    """A parentless commit holding exactly `files` ({path: text})."""
    index = tempfile.mktemp(prefix="test-index-")
    env = dict(os.environ, GIT_INDEX_FILE=index)
    try:
        for path, text in files.items():
            blob = run("hash-object", "-w", "--stdin", input=text.encode()).strip()
            REAL_RUN(["git", "update-index", "--add", "--cacheinfo", f"100644,{blob},{path}"],
                     check=True, env=env)
        tree = REAL_RUN(["git", "write-tree"], check=True, capture_output=True,
                        env=env).stdout.decode().strip()
        return run("commit-tree", tree, "-m", message).strip()
    finally:
        if os.path.exists(index):
            os.unlink(index)


class ComposeOnWindowsNewlines(unittest.TestCase):
    def setUp(self):
        self.cwd = os.getcwd()
        self.dir = tempfile.TemporaryDirectory()
        os.chdir(self.dir.name)
        run("init", "-q")
        run("config", "user.name", "test")
        run("config", "user.email", "test@example.invalid")

    def tearDown(self):
        os.chdir(self.cwd)
        self.dir.cleanup()

    def test_plugin_core_files_and_the_pin_land_exactly(self):
        upstream = commit({"engine/main.c": "int main(void) { return 0; }\n"}, "upstream")
        pc = commit({
            "enginehost/wrapper.txt": "wrapper\n",
            "enginehost/lines/demo/line.json": "{}\n",
            "enginehost/lines/demo/root/bundle-metadata.json": '{"line": "demo"}\n',
        }, "plugin-core")

        with mock.patch.object(subprocess, "run", windows_text_mode):
            tree, applied = plugin_line.compose_tree(pc, upstream, "1.0", "demo")

        self.assertEqual(applied, [])
        paths = run("ls-tree", "-r", "--name-only", tree).splitlines()
        for path in ("engine/main.c", "enginehost/wrapper.txt",
                     "enginehost/lines/demo/root/bundle-metadata.json",
                     "bundle-metadata.json", plugin_line.LINE_FILE):
            self.assertIn(path, paths)
        self.assertFalse([p for p in paths if "\r" in p], paths)
        pin = run("show", f"{tree}:{plugin_line.LINE_FILE}")
        self.assertNotIn("\r", pin)
        self.assertEqual(json.loads(pin)["pluginCore"], pc)


if __name__ == "__main__":
    unittest.main()
