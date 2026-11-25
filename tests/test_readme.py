import json
import re
import unittest
from pathlib import Path

import helpers  # noqa: F401  (puts scripts/ on the path)
from gl import texts, version

ROOT = Path(__file__).resolve().parent.parent


def read(name):
    return (ROOT / name).read_bytes().decode("utf-8")


class ReadmeTests(unittest.TestCase):
    def test_table_of_commands(self):
        rows = re.findall(r"(?m)^\| `/([a-z-]+)` \|(?: `(.*?)`)? \| (.*) \|$", read("README.md"))
        self.assertEqual(rows, [(name, hint, text) for name, (_, hint, text) in texts.COMMANDS.items()])

    def test_installation_matches_the_manifests(self):
        market = json.loads(read(".claude-plugin/marketplace.json"))
        plugin = json.loads(read(".claude-plugin/plugin.json"))
        text = read("README.md")
        self.assertIn("/plugin marketplace add <owner>/" + market["name"], text)
        self.assertIn("/plugin install %s@%s" % (plugin["name"], market["name"]), text)

    def test_manifests_have_what_the_validation_asks_for(self):
        contributors = {"name": "guided-learning-workflow contributors"}
        plugin = json.loads(read(".claude-plugin/plugin.json"))
        market = json.loads(read(".claude-plugin/marketplace.json"))
        self.assertTrue(plugin["description"])
        self.assertEqual(plugin["author"], contributors)
        self.assertTrue(market["description"])
        self.assertEqual(market["owner"], contributors)

    def test_files_named_in_the_readme_exist(self):
        names = re.findall(r"\]\(([^)#:]+)\)", read("README.md"))
        self.assertTrue(names)
        for name in names:
            self.assertTrue((ROOT / name).exists(), name)

    def test_the_phase_files_are_committed_before_the_merge(self):
        step = re.search(r"(?m)^7\. .*$", read("README.md")).group(0)
        self.assertLess(step.index("/finish-phase 1"), step.index("commit"))
        self.assertLess(step.index("commit"), step.index("Merge"))

    def test_what_was_not_tried_on_macos_is_named(self):
        self.assertRegex(read("README.md"), r"macOS[^\n]*upper and lower case")

    def test_changelog_has_the_version(self):
        self.assertIn("## " + version.VERSION, read("CHANGELOG.md"))


if __name__ == "__main__":
    unittest.main()
