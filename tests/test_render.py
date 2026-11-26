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

    def test_gone_todos_with_a_failing_test_is_in_progress_and_names_it(self):
        s = script(1, "Moth", ["1.1"], ["MothTests.A", "MothTests.B"])
        res = {"results": {"Unit": suite_result({"MothTests.A": "passed", "MothTests.B": "failed"})}}
        text = self.show(plan([s]), {"src/Moth.cs": shell([])}, res)
        self.assertEqual(text.splitlines()[1], "  Owner 1 Moth  in progress  tests 1/2  failing: MothTests.B")

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

    def test_then_line_without_targets(self):
        s = script(1, "Moth", ["1.1"], [])
        text = self.show(plan([s]), {"src/Moth.cs": shell(["1.1"])})
        self.assertIn("\nThen: wrap-up\n", text)
        self.assertNotIn("tune", text)

    def test_then_line_with_targets_and_tuning_off(self):
        s = script(1, "Moth", ["1.1"], [])
        root = helpers.make_project(self.tmp, phases={2: {"state": {"status": "build", "branch": "stage-2",
                                                                    "turn": "owner", "part": 0},
                                                          "plan": plan([s], targets=TARGETS[:1])}},
                                    files={"src/Moth.cs": shell(["1.1"])}, settings={"tuning": False})
        text = render.status(state.compute(project.find(root), 2))
        self.assertIn("\nThen: tune (0 of 1 target), wrap-up\n", text)

    def test_tune_and_wrap_up(self):
        s = script(1, "Moth", ["1.1"], [])
        files = {"src/Moth.cs": shell([])}
        tune = self.show(plan([s], targets=TARGETS), files, {"results": {"Unit": suite_result({"x.y": "passed"})}})
        self.assertTrue(tune.startswith("Phase 2 - tune "))
        self.assertIn("Then: wrap-up", tune)
        self.assertIn(texts.target_open("a"), tune)
        self.assertNotIn(texts.SURPRISED_MISSING, tune)   # "Then: wrap-up" covers it
        self.assertTrue(tune.endswith(texts.next_line("summarize-phase", 2) + "\n"))
        stored = {"results": {"Unit": suite_result({"x.y": "passed"})},
                  "log": [{"kind": "rating", "concept": "ai", "rating": "with help"}]}
        open_ = self.show(plan([s]), files, stored)
        self.assertIn(texts.SURPRISED_MISSING, open_)
        self.assertTrue(open_.endswith(texts.next_line("summarize-phase", 2) + "\n"))
        helpers.make_project(self.tmp, phases={2: {"md": helpers.FULL_MD}})
        p = dict(plan([s]), questions=[{"id": "q1", "concept": "ai", "text": "?", "points": ["x"]}])
        changed = self.show(p, files, dict(stored, planHash="0" * 64))
        self.assertIn(texts.plan_changed(2, "phase-2.plan.json"), changed)
        self.assertTrue(changed.endswith(texts.next_line("approve-phase", 2) + "\n"))
        wrap = self.show(p, files, stored)
        self.assertTrue(wrap.startswith("Phase 2 - wrap-up "))
        self.assertTrue(wrap.endswith(texts.next_line("finish-phase", 2) + "\n"))

    def test_planning_done_and_skipped(self):
        s = script(1, "Moth", ["1.1"], [])
        planning = self.show(plan([s]), {}, {"status": "planning"})
        self.assertTrue(planning.endswith(texts.next_line("start-phase", 2) + "\n"))   # the plan has gaps
        planning = self.show(helpers.full_plan(), {}, {"status": "planning"})
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


APP = texts.Words("app", "performance")
D = texts.DEFAULT_WORDS


class WordsTests(unittest.TestCase):
    """Each text with the default words is today's text, word for word; with other words it uses them."""

    def test_gap_no_target(self):
        self.assertEqual(texts.gap_no_target(D), "No balance target.")
        self.assertEqual(texts.gap_no_target(APP), "No performance target.")

    def test_planning_started(self):
        self.assertEqual(texts.planning_started(2, "P", "M", D, True), (
            'Phase 2 is being planned. No code is written in this step.\nPlan it with the owner and fill in P: concepts, '
            'owner scripts (3 to 5, each with path, concept, TODO numbers and tests), parts with tasks, balance targets '
            '(measure, settings, min or max) and wrap-up questions with points. Decisions go to "Notes for later" in '
            'M.\nThe owner accepts the plan with /approve-phase 2, which checks that all of this is there.'))
        self.assertIn(" performance targets (measure", texts.planning_started(2, "P", "M", APP, True))

    def test_score_balance(self):
        self.assertEqual(texts.score_balance(2, 3, D), "Balance: 2/3 targets met.")
        self.assertEqual(texts.score_balance(2, 3, APP), "Performance: 2/3 targets met.")
        self.assertEqual(texts.score_balance(0, 1, texts.Words("app", "real-time")), "Real-time: 0/1 targets met.")

    def test_capitalized(self):
        self.assertEqual([texts.capitalized(w) for w in ("balance", "web app", "x", "iOS")],
                         ["Balance", "Web app", "X", "IOS"])

    def test_setup_texts(self):
        self.assertEqual(texts.setup_settings_by_hand(D), (
            "This game was set up before, so its own settings count. To change one, the owner edits "
            ".claude/learning/project.json by hand."))
        self.assertTrue(texts.setup_settings_by_hand(APP).startswith("This app was set up before"))
        self.assertEqual(texts.setup_key("docs", True, D), (
            '"docs" is wrong. It must be a folder of the game for the phase files, like "Docs/learning", '
            'and not in .claude.'))
        self.assertEqual(texts.setup_key("code", False, D),
                         '"code" is missing. It must be a list of code folders of the game, like ["src"].')
        self.assertIn("code folders of the app", texts.setup_key("code", False, APP))
        self.assertEqual(texts.setup_elsewhere("R", D),
                         "This folder is inside the game at R, which is set up already. Run setup there.")
        self.assertIn("inside the app at R", texts.setup_elsewhere("R", APP))
        self.assertEqual(texts.setup_ignored(D), (
            "Git ignores .claude/learning/project.json because of a line in .gitignore, so the settings would not be "
            "saved with the game. Change that line. With .claude/ for example: write .claude/* and below it "
            "!.claude/learning/"))
        self.assertIn("saved with the app.", texts.setup_ignored(APP))

    def test_rehearsal_texts(self):
        self.assertEqual(texts.rehearsal_short(4, D), "REHEARSAL run 4. This is the fake project, not your game.")
        self.assertEqual(texts.rehearsal_short(4, APP), "REHEARSAL run 4. This is the fake project, not your app.")
        self.assertTrue(texts.rehearsal_rules(4, "S", D).endswith("use no git, and leave the real game alone."))
        self.assertTrue(texts.rehearsal_rules(4, "S", APP).endswith("use no git, and leave the real app alone."))

    def test_no_game_word_left(self):
        """Only DEFAULT_WORDS may say game or balance; comments and docstrings do not count."""
        import ast
        tree = ast.parse(Path(texts.__file__).read_text(encoding="utf-8"))
        docstrings = {id(n.body[0].value) for n in ast.walk(tree)
                      if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef)) and n.body
                      and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
        found = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)
                 and id(n) not in docstrings and re.search(r"\b(game|games|balance)\b", n.value, re.I)]
        self.assertEqual(sorted(found), ["balance", "game"], found)


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
        self.assertEqual(texts.next_line("setup-learning", None), "Next: /setup-learning  (step 0: once per project)")

    def test_steps_run_from_zero_to_five(self):
        steps = [v[0] for v in texts.COMMANDS.values()]
        self.assertEqual([s[:7] for s in steps], ["step %d:" % i for i in range(6)])


if __name__ == "__main__":
    unittest.main()
