import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import helpers
from helpers import PROJECT_JSON
from gl import project, setup, store, texts

ROOT = Path(__file__).resolve().parent.parent
LEARNING = ROOT / "scripts" / "learning.py"
IGNORED = (ROOT / "templates" / "gitignore.txt").read_text(encoding="utf-8").split()
START = "<!-- guided-learning:start -->"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = self.tmp / "Lantern Keeper"
        self.root.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def files(self):
        return {p.relative_to(self.root).as_posix(): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}

    def put(self, rel, raw):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)

    def apply(self, changed=None, **kw):
        return setup.apply(self.root, dict(PROJECT_JSON, **(changed or {})), **kw)

    def refused(self, settings):
        before = self.files()
        with self.assertRaises(setup.SetupError) as caught:
            setup.apply(self.root, settings, claudeMd=True)
        self.assertEqual(self.files(), before)
        return str(caught.exception)


class ApplyTests(Base):
    def test_setup_writes_the_files(self):
        done = self.apply()
        files = self.files()
        self.assertEqual(set(files), {".claude/learning/project.json", ".claude/learning/config.json",
                                      "Docs/learning/README.md", ".gitignore"})
        self.assertEqual(json.loads(files[".claude/learning/project.json"].decode("utf-8")), PROJECT_JSON)
        self.assertEqual(json.loads(files[".claude/learning/config.json"].decode("utf-8")), {"rehearsal": False})
        self.assertEqual(files["Docs/learning/README.md"], (ROOT / "templates" / "README.md").read_bytes())
        self.assertEqual(files[".gitignore"].decode("utf-8").split("\n"), IGNORED + [""])
        for name, raw in files.items():
            self.assertNotIn(b"\r", raw)
            self.assertTrue(any(name in line for line in done), name)
        found = project.find(str(self.root))
        self.assertEqual((found.rehearsal, found.problem), (False, None))

    def test_setup_twice_is_the_same(self):
        self.apply(claudeMd=True)
        before = self.files()
        done = self.apply(claudeMd=True)
        self.assertEqual(self.files(), before)
        self.assertIn(texts.setup_kept(".claude/learning/project.json"), done)
        self.assertIn(texts.SETUP_SETTINGS_BY_HAND, done)

    def test_existing_files_are_not_overwritten(self):
        raw = json.dumps(dict(PROJECT_JSON, docs="Notes", background="Java")).encode("utf-8")
        self.put(".claude/learning/project.json", raw)
        self.put(".claude/learning/config.json", b'{"rehearsal": true}')
        self.put("Notes/README.md", b"mine\r\n")
        self.apply()
        files = self.files()
        self.assertEqual(files[".claude/learning/project.json"], raw)
        self.assertEqual(files[".claude/learning/config.json"], b'{"rehearsal": true}')
        self.assertEqual(files["Notes/README.md"], b"mine\r\n")
        self.assertNotIn("Docs/learning/README.md", files)

    def test_missing_files_of_an_existing_project_are_added(self):
        self.apply()
        for rel in (".claude/learning/config.json", "Docs/learning/README.md", ".gitignore"):
            (self.root / rel).unlink()
        self.apply()
        self.assertEqual(len(self.files()), 4)

    def test_claude_md_untouched_without_agreement(self):
        self.put("CLAUDE.md", b"# Rules\r\n")
        self.apply()
        self.assertEqual(self.files()["CLAUDE.md"], b"# Rules\r\n")

    def test_no_claude_md_is_made_without_agreement(self):
        self.apply()
        self.assertFalse((self.root / "CLAUDE.md").exists())

    def test_claude_md_section_is_added_after_the_text_that_is_there(self):
        section = (ROOT / "templates" / "claude-md-section.md").read_text(encoding="utf-8")
        for raw, newline in ((None, "\n"), (b"# Rules\r\nBe kind", "\r\n"), (b"# Rules\nBe kind\n", "\n"), (b"", "\n")):
            with self.subTest(raw):
                if raw is not None:
                    self.put("CLAUDE.md", raw)
                self.apply(claudeMd=True)
                text = self.files()["CLAUDE.md"].decode("utf-8")
                expected = "# Rules\nBe kind\n\n" + section if raw else section
                self.assertEqual(text, expected.replace("\n", newline))
                self.apply(claudeMd=True)
                self.assertEqual(self.files()["CLAUDE.md"].decode("utf-8"), text)

    def test_a_section_with_one_marker_left_is_not_added_again(self):
        for mark in (START, "<!--guided-learning:END-->"):
            raw = ("# Rules\n%s\nmine\n" % mark).encode("utf-8")
            self.put("CLAUDE.md", raw)
            done = self.apply(claudeMd=True)
            self.assertEqual(self.files()["CLAUDE.md"], raw)
            self.assertIn(texts.SETUP_SECTION_THERE, done)

    def test_existing_gitignore_lines_kept(self):
        for raw, newline in ((b"\xef\xbb\xbf*.log\r\n\r\n# mine\r\nbuild/", "\r\n"),
                             (b"*.log\n\n# mine\nbuild/\n", "\n")):
            with self.subTest(raw):
                self.put(".gitignore", raw)
                self.apply()
                old = raw if raw.endswith(b"\n") else raw + newline.encode()
                self.assertEqual(self.files()[".gitignore"], old + (newline.join(IGNORED) + newline).encode())

    def test_only_missing_gitignore_lines_are_added(self):
        self.put(".gitignore", ("\ufeff%s\n  \n%s  \n" % (IGNORED[0], IGNORED[2])).encode("utf-8"))
        self.apply()
        lines = self.files()[".gitignore"].decode("utf-8-sig").split()
        self.assertEqual(sorted(lines), sorted(IGNORED))

    def test_a_missing_code_folder_is_named(self):
        done = self.apply({"code": ["src", "game/src"]})
        self.assertIn(texts.setup_no_folder("src"), done)
        (self.root / "src").mkdir()
        done = self.apply({"code": ["src", "game/src"]})
        self.assertNotIn(texts.setup_no_folder("src"), done)
        self.assertIn(texts.setup_no_folder("game/src"), done)

    def test_project_json_is_written_last(self):
        written = []
        real = store.write_text

        def note(path, text):
            written.append(Path(path).name)
            real(path, text)

        with mock.patch.object(setup.store, "write_text", note):
            self.apply(claudeMd=True)
        self.assertEqual((len(written), written[-1]), (5, "project.json"))

    def test_a_linked_file_stays_a_link(self):
        target = self.tmp / "AGENTS.md"
        target.write_bytes(b"# Agents\n")
        try:
            os.symlink(target, self.root / "CLAUDE.md")
        except (OSError, NotImplementedError):
            self.skipTest("no symbolic links here")
        self.apply(claudeMd=True)
        self.assertTrue((self.root / "CLAUDE.md").is_symlink())
        self.assertIn(START.encode(), target.read_bytes())


class ValidationTests(Base):
    BAD = {
        "docs": [".claude", ".claude/learning", ".Claude/docs", "", " ", None, 3, "/etc",
                 "C:/x", "../x", "a/../../x", "a\\b", "~/x", ".", "a//b", " a"],
        "code": ["src", [], [""], [1], None, ["/src"], ["../src"], ["src", "C:\\src"], ["src\\game"]],
        "extensions": [".cs", [], ["cs"], ["*.cs"], ["."], [1], None, [". cs"]],
        "ownerMark": ["", "  ", None, 1, "two\nlines"],
        "suites": ["Unit", [], [""], [2], None, ["Unit", "Unit"]],
        "background": ["", None, []],
    }

    def test_each_wrong_value_is_refused_and_named(self):
        for key, values in self.BAD.items():
            for value in values:
                with self.subTest(key=key, value=value):
                    self.assertIn('"%s"' % key, self.refused(dict(PROJECT_JSON, **{key: value})))

    def test_each_missing_key_is_named(self):
        text = self.refused({})
        for key in PROJECT_JSON:
            self.assertIn('"%s"' % key, text)

    def test_unknown_key_is_refused(self):
        self.assertIn('"ownermark"', self.refused(dict(PROJECT_JSON, ownermark="x")))

    def test_good_values(self):
        for changed in ({"code": ["."]}, {"code": ["Assets/Scripts", "Tests/"]},
                        {"extensions": [".cs", ".blade.php", ".h++"]},
                        {"docs": "Docs/Lernen \u00fc"}, {"suites": ["EditMode", "PlayMode"]}):
            self.assertEqual(setup.problems(dict(PROJECT_JSON, **changed)), [], changed)

    def test_docs_that_is_a_file_is_refused(self):
        self.put("Docs", b"x")
        self.assertIn("Docs", self.refused(PROJECT_JSON))

    def test_a_file_in_the_way_of_the_learning_folder_is_refused(self):
        for rel in (".claude", ".claude/learning"):
            with self.subTest(rel):
                self.put(rel, b"x")
                self.assertIn(rel, self.refused(PROJECT_JSON))
                (self.root / rel).unlink()

    def test_a_text_file_that_is_not_utf8_is_refused(self):
        for name in (".gitignore", "CLAUDE.md"):
            with self.subTest(name):
                self.put(name, "*.log\n".encode("utf-16"))
                self.assertIn(name, self.refused(PROJECT_JSON))
                (self.root / name).unlink()

    def test_a_wrong_project_json_is_refused_and_named(self):
        self.put(".claude/learning/project.json", b'{"docs": ""}')
        self.assertIn("project.json", self.refused(PROJECT_JSON))
        self.put(".claude/learning/project.json", b"{")
        with self.assertRaises(store.BadJson):
            setup.apply(self.root, PROJECT_JSON)
        self.assertEqual(len(self.files()), 1)


class CliTests(Base):
    def cli(self, *args, cwd=None):
        env = dict(os.environ, GIT_CEILING_DIRECTORIES=str(self.tmp), PYTHONIOENCODING="cp1252")
        done = subprocess.run([sys.executable, str(LEARNING), "setup"] + list(args), cwd=str(cwd or self.root),
                              env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL)
        self.assertEqual(done.stderr, b"")
        return done.returncode, done.stdout.decode("utf-8")

    def settings(self, data=PROJECT_JSON):
        path = self.tmp / "settings.json"
        helpers.write_json(path, data)
        return str(path)

    def test_setup_in_the_working_folder(self):
        code, out = self.cli(self.settings())
        self.assertEqual(code, 0, out)
        self.assertEqual(len(self.files()), 4)
        self.assertEqual(out.rstrip("\n").split("\n")[-1], texts.next_line("start-phase", 1))

    def test_claude_md_flag(self):
        for args in (("--claude-md", self.settings()), (self.settings(), "--claude-md")):
            code, out = self.cli(*args)
            self.assertEqual(code, 0, out)
            self.assertEqual(self.files()["CLAUDE.md"].decode("utf-8").count(START), 1)

    def test_the_project_json_itself_can_be_given(self):
        self.cli(self.settings())
        (self.root / ".gitignore").unlink()
        code, out = self.cli(".claude/learning/project.json")
        self.assertEqual(code, 0, out)
        self.assertIn(".gitignore", self.files())

    def test_an_existing_project_names_its_own_next_command(self):
        helpers.make_project(self.root, {2: {"state": {"status": "planning"}}})
        code, out = self.cli(self.settings())
        self.assertEqual((code, out.rstrip("\n").split("\n")[-1]), (0, texts.next_line("start-phase", 2)))

    def test_a_next_command_that_fails_does_not_hide_what_was_done(self):
        helpers.make_project(self.root, {1: {"state": {}}})
        (self.root / "Docs/learning/phase-1.json").write_bytes(b"{")
        code, out = self.cli(self.settings())
        self.assertEqual(code, 0, out)
        self.assertEqual(out.split("\n")[0], texts.setup_written("Docs/learning/README.md"))
        self.assertNotIn("Next:", out)

    def test_bad_settings_and_bad_calls_write_nothing(self):
        bad = self.tmp / "bad.json"
        bad.write_bytes(b"{ nope")
        wrong = self.tmp / "wrong.json"
        helpers.write_json(wrong, dict(PROJECT_JSON, code=[]))
        good = self.settings()
        for args in ((str(wrong),), (str(bad),), (str(self.tmp / "none.json"),), (), ("--claude-md",),
                     (good, "more"), (good, "--claude")):
            with self.subTest(args):
                code, out = self.cli(*args)
                self.assertEqual(code, 1)
                self.assertNotIn("Error", out)
                self.assertEqual(self.files(), {})

    def test_a_folder_inside_another_game_is_refused(self):
        self.cli(self.settings())
        before = self.files()
        sub = self.root / "src"
        sub.mkdir()
        code, out = self.cli(self.settings(), cwd=sub)
        self.assertEqual(code, 1)
        self.assertIn(str(project.find(str(sub)).root), out)
        self.assertEqual(self.files(), before)


if __name__ == "__main__":
    unittest.main()
