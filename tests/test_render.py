import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import helpers
from helpers import plan, script, shell, suite_result
from gl import project, render, state, texts, version

DESIGN = (Path(__file__).resolve().parent.parent / "docs" / "design.md").read_text(encoding="utf-8")
TARGETS = [{"id": "a", "text": "A", "measure": "m", "settings": [], "min": 1, "max": 2},
           {"id": "b", "text": "B", "measure": "m", "settings": [], "min": 1, "max": 2}]


def design_rows(heading):
    """The table rows (cells without backticks) of the design section starting at heading."""
    section = DESIGN.split(heading, 1)[1].split("\n#", 1)[0]
    rows = []
    for line in section.splitlines():
        if line.startswith("|") and not line.startswith("|---") and "Command" not in line:
            rows.append([c.strip().strip("`").strip() for c in line.strip().strip("|").split("|")])
    return rows


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        patcher = mock.patch.object(state, "current_branch", return_value="stage-2")
        patcher.start()
        self.addCleanup(patcher.stop)

    def show(self, plan_, files, stored=None):
        st = {"status": "build", "branch": "stage-2", "turn": "owner", "part": 0}
        st.update(stored or {})
        root = helpers.make_project(self.tmp, phases={2: {"state": st, "plan": plan_}}, files=files)
        return render.status(state.compute(project.find(root), 2))


class StatusTextTests(Base):
    def test_status_text_exactly(self):
        scripts = [script(1, "Charger", ["1.1", "1.2"], ["ChargerTests.A", "ChargerTests.B"]),
                   script(2, "Shooter", ["2.1", "2.2", "2.3", "2.4"], ["ShooterTests.A", "ShooterTests.B"]),
                   script(3, "Orbit blades", ["3.1", "3.2"], [])]
        files = {"src/Charger.cs": shell([]), "src/Shooter.cs": shell(["2.3", "2.4"]),
                 "src/Orbit blades.cs": shell(["3.1", "3.2"])}
        results = {"Unit": suite_result({"ChargerTests.A": "passed", "ChargerTests.B": "passed",
                                         "ShooterTests.A": "passed", "ShooterTests.B": "failed"})}
        log = [{"kind": "help", "script": 1, "level": 1}]
        text = self.show(plan(scripts, targets=TARGETS), files, {"results": results, "log": log})
        self.assertEqual(text, "\n".join([
            "Phase 2 - build         4 of 8 TODOs done",
            "  Owner 1 Charger       done         tests 2/2  help: 1",
            "  Owner 2 Shooter       2 of 4       tests 1/2  <- next: TODO 2.3",
            "  Owner 3 Orbit blades  not started",
            "Then: tune (0 of 2 targets), wrap-up",
            "Your turn (part 1 of 1).",
            "Next: /summarize-phase 2  (step 4: your turn)",
        ]) + "\n")

    def test_ai_turn_names_build_phase(self):
        text = self.show(plan([script(1, "Moth", ["1.1"], [])]), {}, {"turn": None})
        self.assertIn("It is the AI's turn", text)
        self.assertIn("/build-phase", text)
        self.assertTrue(text.endswith(texts.next_line("build-phase", 2) + "\n"))

    def test_unknown_says_why(self):
        s = script(1, "Moth", ["1.1"], ["MothTests.A"])
        old = {"results": {"Unit": suite_result({"MothTests.A": "passed"}, helpers.OLD)}}
        text = self.show(plan([s]), {"src/Moth.cs": shell([])}, old)
        self.assertIn(texts.WHY["old"], text)

    def test_wrong_branch_shows_only_that(self):
        s = script(1, "Moth", ["1.1"], [])
        with mock.patch.object(state, "current_branch", return_value="main"):
            text = self.show(plan([s]), {"src/Moth.cs": shell(["1.1"])})
        self.assertEqual(text, "\n".join([
            "Phase 2 - build",
            "Wrong branch: this phase is on stage-2, but main is checked out. Switch with: git switch stage-2",
            "Next: /summarize-phase 2  (step 4: your turn)",
        ]) + "\n")

    def test_lost_todo_and_problem_are_shown(self):
        s = script(1, "Moth", ["1.1", "1.2"], [])
        text = self.show(plan([s]), {"src/Moth.cs": shell(["1.1"])}, {"turn": None})
        self.assertIn(texts.lost_todo("1.2", "Owner 1 Moth", "src/Moth.cs"), text)

    def test_tune_and_wrap_up(self):
        s = script(1, "Moth", ["1.1"], [])
        files = {"src/Moth.cs": shell([])}
        tune = self.show(plan([s], targets=TARGETS), files, {"results": {"Unit": suite_result({"x.y": "passed"})}})
        self.assertTrue(tune.startswith("Phase 2 - tune "))
        self.assertIn("Then: wrap-up", tune)
        self.assertIn(texts.target_open("a"), tune)
        wrap = self.show(plan([s]), files, {"results": {"Unit": suite_result({"x.y": "passed"})}})
        self.assertTrue(wrap.startswith("Phase 2 - wrap-up "))
        self.assertTrue(wrap.endswith(texts.next_line("finish-phase", 2) + "\n"))

    def test_planning_done_and_skipped(self):
        s = script(1, "Moth", ["1.1"], [])
        planning = self.show(plan([s]), {}, {"status": "planning"})
        self.assertTrue(planning.endswith(texts.next_line("approve-phase", 2) + "\n"))
        done = self.show(plan([s]), {}, {"status": "done"})
        self.assertTrue(done.startswith("Phase 2 - done\n"))
        self.assertTrue(done.endswith(texts.next_line("start-phase", 3) + "\n"))
        skipped = self.show(plan([s]), {}, {"status": "skipped"})
        self.assertTrue(skipped.startswith("Phase 2 - skipped\n"))


class OneLineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        for p in (mock.patch("gl.version.plugin_hash", return_value="a1b2c3"),
                  mock.patch("gl.version.VERSION", "0.1.0")):
            p.start()
            self.addCleanup(p.stop)
        row = [r for r in design_rows("## Rehearsal") if r[0] == "Status line"][0]
        self.off, self.on = row[1], row[2]

    def project(self, rehearsal):
        root = helpers.make_project(self.tmp)
        if rehearsal:
            helpers.set_switch(root, '{"rehearsal": true}')
        return project.find(root), root

    def test_one_line_real(self):
        proj, _ = self.project(False)
        self.assertEqual(render.one_line(proj), self.off)

    def test_one_line_rehearsal(self):
        proj, root = self.project(True)
        helpers.write_json(root / ".claude" / "learning" / "local" / "seen.json", {"mtime": 1.0, "run": 4})
        self.assertEqual(render.one_line(proj), self.on)

    def test_rehearsal_without_seen_file_is_run_one(self):
        proj, _ = self.project(True)
        self.assertEqual(render.one_line(proj), "Learning hooks: on (REHEARSAL run 1, 0.1.0 a1b2c3)")

    def test_a_problem_is_said(self):
        proj, root = self.project(False)
        helpers.set_switch(root, "{broken")
        proj = project.find(root)
        line = render.one_line(proj)
        self.assertTrue(line.startswith(self.off))
        self.assertIn(proj.problem, line)

    def test_real_hash_is_used_without_patch(self):
        mock.patch.stopall()
        proj, _ = self.project(False)
        self.assertRegex(render.one_line(proj), r"^Learning hooks: on \(\d+\.\d+\.\d+ [0-9a-f]{6}\)$")


class TextTests(unittest.TestCase):
    def test_descriptions_match_the_design(self):
        rows = design_rows("### Descriptions")
        self.assertEqual(len(rows), 6)
        self.assertEqual(len(texts.COMMANDS), 6)
        for command, hint, description in rows:
            _, got_hint, got_description = texts.COMMANDS[command.lstrip("/")]
            self.assertEqual((got_hint, got_description), (hint, description), command)

    def test_next_line(self):
        self.assertEqual(texts.next_line("summarize-phase", 2), "Next: /summarize-phase 2  (step 4: your turn)")
        self.assertEqual(texts.next_line("setup-learning", None), "Next: /setup-learning  (step 0: once per game)")

    def test_steps_run_from_zero_to_five(self):
        steps = [v[0] for v in texts.COMMANDS.values()]
        self.assertEqual([s[:7] for s in steps], ["step %d:" % i for i in range(6)])


if __name__ == "__main__":
    unittest.main()
