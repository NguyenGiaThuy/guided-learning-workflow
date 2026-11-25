import os
import shutil
import tempfile
import unittest
from pathlib import Path

import helpers
from gl import project, render, store, texts


class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = helpers.make_project(self.tmp, phases={
            2: {"state": {"status": "build"}, "plan": {"phase": 2}, "md": "# x\n"},
            10: {"state": {"status": "done"}},
            1: {"state": {"status": "done"}},
        })

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_no_project_json_is_none(self):
        empty = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, empty, True)
        self.assertIsNone(project.find(empty))

    def test_found_from_a_subfolder(self):
        sub = self.root / "src" / "deep"
        sub.mkdir(parents=True)
        self.assertEqual(project.find(sub).root, self.root.resolve())

    def test_settings_and_paths(self):
        p = project.find(self.root)
        self.assertEqual(p.settings["suites"], ["Unit"])
        self.assertEqual(p.docs, self.root.resolve() / "Docs" / "learning")
        self.assertEqual(p.code_dirs, [self.root.resolve() / "src"])
        self.assertEqual(p.phase_numbers(), [1, 2, 10])
        self.assertEqual(p.state_path(2).name, "phase-2.json")
        self.assertEqual(p.plan_path(2).name, "phase-2.plan.json")
        self.assertEqual(p.md_path(2).name, "phase-2.md")

    def test_switch_missing_is_off(self):
        p = project.find(self.root)
        self.assertFalse(p.rehearsal)
        self.assertIsNone(p.problem)
        self.assertIs(p.active, p)

    def test_switch_broken_is_off_and_says_so(self):
        for text in ("{nope", "[true]", '{"rehearsal": "yes"}',
                     '{"rehearsal": true}'.encode("utf-16"), b'{"rehearsal": \xff}'):
            helpers.set_switch(self.root, text)
            p = project.find(self.root)
            self.assertFalse(p.rehearsal, text)
            self.assertIn("config.json", p.problem, text)
            self.assertIs(p.active, p)

    def test_switch_that_cannot_be_read_is_off(self):
        (self.root / ".claude" / "learning" / "config.json").mkdir()
        p = project.find(self.root)
        self.assertFalse(p.rehearsal)
        self.assertIn("config.json", p.problem)

    @unittest.skipUnless(os.name == "nt", "case-insensitive file system")
    def test_rehearsal_folder_name_is_matched_ignoring_case(self):
        helpers.set_switch(self.root, '{"rehearsal": true}')
        reh = self.root / ".claude" / "learning" / "Rehearsal"
        helpers.make_project(reh, settings={"docs": "docs"})
        self.assertEqual(project.find(reh / "src").root, self.root.resolve())

    def test_bom_and_crlf_are_read(self):
        helpers.set_switch(self.root, b'\xef\xbb\xbf{\r\n"rehearsal": true\r\n}\r\n')
        p = project.find(self.root)
        self.assertTrue(p.rehearsal)
        self.assertIsNone(p.problem)

    def test_switch_on_makes_rehearsal_active(self):
        helpers.set_switch(self.root, '{"rehearsal": true}')
        p = project.find(self.root)
        want = self.root.resolve() / ".claude" / "learning" / "rehearsal"
        self.assertTrue(p.rehearsal)
        self.assertEqual(p.active.root, want)  # the folder does not exist yet: no crash

    def test_rehearsal_project_is_its_own_active_and_found_from_inside(self):
        helpers.set_switch(self.root, '{"rehearsal": true}')
        reh = self.root / ".claude" / "learning" / "rehearsal"
        helpers.make_project(reh, settings={"docs": "docs"})
        p = project.find(reh / "src")
        self.assertEqual(p.root, self.root.resolve())
        a = p.active
        self.assertEqual(a.root, reh.resolve())
        self.assertEqual(a.docs, reh.resolve() / "docs")
        self.assertIs(a.active, a)
        self.assertFalse(a.rehearsal)

    def test_bad_project_json_names_file_and_line(self):
        (self.root / ".claude" / "learning" / "project.json").write_text("{\n\n", encoding="utf-8")
        with self.assertRaises(store.BadJson) as cm:
            project.find(self.root)
        self.assertIn("project.json", str(cm.exception))

    BAD = {"docs": ["Docs", 5, "", "../x"], "code": ["src", [], [5], ["../src"]], "extensions": [".cs", ["cs"]],
           "ownerMark": ["", 5], "suites": ["Unit", []], "background": [None]}

    def test_wrong_settings_are_an_error_that_names_file_and_key(self):
        pj = self.root / ".claude" / "learning" / "project.json"
        for key, values in self.BAD.items():
            for value in values:
                if (key, value) == ("docs", "Docs"):
                    continue
                helpers.write_json(pj, dict(helpers.PROJECT_JSON, **{key: value}))
                with self.assertRaises(store.BadJson) as cm:
                    project.find(self.root)
                self.assertIn("project.json", str(cm.exception), (key, value))
                self.assertIn(texts.setup_key(key, True), str(cm.exception), (key, value))
        for data in ({}, {k: v for k, v in helpers.PROJECT_JSON.items() if k != "code"}):
            helpers.write_json(pj, data)
            with self.assertRaises(store.BadJson) as cm:
                project.find(self.root)
            self.assertIn(texts.setup_key("code", False), str(cm.exception))
        helpers.write_json(pj, dict(helpers.PROJECT_JSON, codes=["src"]))
        with self.assertRaises(store.BadJson) as cm:
            project.find(self.root)
        self.assertIn(texts.setup_unknown("codes"), str(cm.exception))

    def test_wrong_settings_of_the_rehearsal_are_an_error(self):
        helpers.set_switch(self.root, '{"rehearsal": true}')
        reh = self.root / ".claude" / "learning" / "rehearsal"
        helpers.make_project(reh)
        helpers.write_json(reh / ".claude" / "learning" / "project.json", dict(helpers.PROJECT_JSON, code="src"))
        found = project.find(self.root)
        with self.assertRaises(store.BadJson):
            found.active

    def test_a_missing_code_folder_is_in_the_status_line(self):
        self.assertNotIn("does not exist", render.one_line(project.find(self.root)))
        pj = self.root / ".claude" / "learning" / "project.json"
        helpers.write_json(pj, dict(helpers.PROJECT_JSON, code=["src", "Src2", "game/code"]))
        line = render.one_line(project.find(self.root))
        self.assertTrue(line.startswith("Learning hooks: on ("), line)
        for folder in ("Src2", "game/code"):
            self.assertIn(texts.setup_no_folder(folder), line)
        self.assertNotIn(texts.setup_no_folder("src"), line)
        self.assertNotIn("\n", line)
        helpers.set_switch(self.root, "{")
        line = render.one_line(project.find(self.root))
        self.assertIn("config.json", line)
        self.assertIn(texts.setup_no_folder("Src2"), line)


if __name__ == "__main__":
    unittest.main()
