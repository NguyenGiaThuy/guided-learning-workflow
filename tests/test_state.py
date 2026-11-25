import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import helpers
from helpers import FRESH, OLD, plan, script, shell, suite_result
from gl import project, state, texts

TESTS = ["MothTests.Turns", "MothTests.Dies"]
ALL = ["1.1", "1.2", "1.3", "1.4", "1.5"]
PASS = {"MothTests.Turns": "passed", "MothTests.Dies": "passed"}


def moth(tests=TESTS):
    return script(1, "Moth", ALL, tests)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        patcher = mock.patch.object(state, "current_branch", return_value="stage-2")
        patcher.start()
        self.addCleanup(patcher.stop)

    def make(self, plan_, left=ALL, stored=None, files=None, settings=None):
        """Phase 2 in build with the owner's turn, part 0, and Moth's file holding `left`."""
        st = {"status": "build", "branch": "stage-2", "turn": "owner", "part": 0}
        st.update(stored or {})
        code = {"src/Moth.cs": shell(left)}
        code.update(files or {})
        root = helpers.make_project(self.tmp, phases={2: {"state": st, "plan": plan_}},
                                    files=code, settings=settings)
        self.project = project.find(root)
        return self.project

    def compute(self, *args, **kw):
        return state.compute(self.make(*args, **kw), 2)

    def fresh(self, tests=PASS):
        return {"results": {"Unit": suite_result(tests)}}


class ScriptTests(Base):
    def test_nothing_done(self):
        s = self.compute(plan([moth()]))
        sc = s.scripts[0]
        self.assertEqual((s.status, s.turn, sc.status), ("build", "owner", "not started"))
        self.assertEqual((sc.todos_done, sc.todos_total), (0, 5))
        self.assertEqual(s.next_todo, "1.1")
        self.assertIn(texts.todos_left("Owner 1 Moth", 5), s.open_items)

    def test_half_done_names_the_next_todo(self):
        s = self.compute(plan([moth()]), left=["1.3", "1.4", "1.5"])
        sc = s.scripts[0]
        self.assertEqual(sc.status, "in progress")
        self.assertEqual((sc.todos_done, sc.todos_total), (2, 5))
        self.assertEqual(s.next_todo, "1.3")
        self.assertEqual((s.todos_done, s.todos_total), (2, 5))

    def test_next_todo_is_the_first_in_the_file(self):
        s = self.compute(plan([moth()]), left=["1.5", "1.3"])
        self.assertEqual(s.next_todo, "1.5")

    def test_all_todos_gone_but_test_fails_is_in_progress(self):
        res = self.fresh({"MothTests.Turns": "passed", "MothTests.Dies": "failed"})
        s = self.compute(plan([moth()]), left=[], stored=res)
        sc = s.scripts[0]
        self.assertEqual(sc.status, "in progress")
        self.assertEqual((sc.tests_passed, sc.tests_total), (1, 2))
        self.assertIsNone(s.next_todo)

    def test_old_results_are_unknown(self):
        res = {"results": {"Unit": suite_result(PASS, OLD)}}
        s = self.compute(plan([moth()]), left=[], stored=res)
        self.assertEqual(s.scripts[0].status, "unknown")
        self.assertEqual(s.scripts[0].why, "old")
        self.assertEqual(s.status, "build")

    def test_a_test_without_a_result_is_unknown_not_run(self):
        res = self.fresh({"MothTests.Turns": "passed"})
        s = self.compute(plan([moth()]), left=[], stored=res)
        self.assertEqual(s.scripts[0].status, "unknown")
        self.assertEqual(s.scripts[0].why, "not run")

    def test_a_failure_wins_over_a_missing_result(self):
        res = self.fresh({"MothTests.Dies": "failed"})
        s = self.compute(plan([moth()]), left=[], stored=res)
        self.assertEqual(s.scripts[0].status, "in progress")

    def test_namespace_and_cases_are_matched_and_all_cases_must_pass(self):
        res = self.fresh({"Game.MothTests.Turns(1)": "passed", "Game.MothTests.Turns(2)": "failed",
                          "Game.MothTests.Dies": "passed"})
        s = self.compute(plan([moth()]), left=[], stored=res)
        self.assertEqual(s.scripts[0].status, "in progress")
        self.assertEqual(s.scripts[0].tests_passed, 1)

    def test_tests_in_another_suite(self):
        res = {"results": {"Unit": suite_result({"MothTests.Turns": "passed"}),
                           "Play": suite_result({"MothTests.Dies": "passed"})}}
        s = self.compute(plan([moth()]), left=[], stored=res, settings={"suites": ["Unit", "Play"]})
        self.assertEqual(s.scripts[0].status, "done")

    def test_help_level_is_the_highest(self):
        log = [{"kind": "help", "script": 1, "level": 1}, {"kind": "help", "script": 1, "level": 3},
               {"kind": "help", "script": 2, "level": 4}, "junk"]
        s = self.compute(plan([moth()]), left=[], stored=dict(self.fresh(), log=log))
        self.assertEqual(s.scripts[0].help, 3)

    def test_lost_todo_is_reported(self):
        # not handed over yet, and 1.2 and 1.5 were never in the file
        s = self.compute(plan([moth()]), left=["1.1", "1.3", "1.4"], stored={"turn": None})
        sc = s.scripts[0]
        self.assertEqual(s.lost_todos, ["1.2", "1.5"])
        self.assertEqual((sc.status, sc.todos_done), ("not started", 0))
        self.assertTrue(s.problems)

    def test_missing_file_is_never_done(self):
        proj = self.make(plan([script(1, "Moth", ALL, [])]), left=[])
        Path(proj.root, "src", "Moth.cs").unlink()
        s = state.compute(proj, 2)
        sc = s.scripts[0]
        self.assertEqual((sc.status, sc.todos_done), ("not started", 0))
        self.assertEqual(s.problems, [texts.script_file_missing("Owner 1 Moth", "src/Moth.cs")])

    def test_missing_file_before_hand_over_is_no_problem(self):
        proj = self.make(plan([moth()]), stored={"turn": None})
        Path(proj.root, "src", "Moth.cs").unlink()
        s = state.compute(proj, 2)
        self.assertEqual(s.problems, [])
        self.assertFalse(any("src/Moth.cs" in i for i in s.open_items))

    def test_a_todo_that_is_not_in_the_plan_keeps_the_script_open(self):
        plan_ = plan([script(1, "Moth", ["1.1"], [])])
        s = self.compute(plan_, left=["1.9"], stored=self.fresh())
        sc = s.scripts[0]
        self.assertEqual((sc.status, s.next_todo, s.status), ("in progress", "1.9", "build"))
        self.assertEqual((sc.todos_done, sc.todos_total), (1, 1))
        self.assertIn(texts.todos_left("Owner 1 Moth", 1), s.open_items)

    def test_not_started_is_not_started_with_an_unplanned_todo_only_after_planned_ones_go(self):
        s = self.compute(plan([script(1, "Moth", ["1.1"], [])]), left=["1.1", "1.9"])
        self.assertEqual(s.scripts[0].todos_done, 0)

    def test_not_built_yet_is_the_ais_turn(self):
        s = self.compute(plan([moth()]), stored={"turn": None})
        self.assertEqual((s.turn, s.part), ("ai", 0))

    def test_uncommitted_work_counts(self):
        root = self.make(plan([moth()])).root
        git = ["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
        try:
            subprocess.run(git + ["init", "-q"], check=True, capture_output=True)
            subprocess.run(git + ["add", "."], check=True, capture_output=True)
            subprocess.run(git + ["commit", "-q", "-m", "x"], check=True, capture_output=True)
        except (OSError, subprocess.CalledProcessError):
            self.skipTest("git is not available")
        (root / "src" / "Moth.cs").write_bytes(shell(["1.4", "1.5"]).encode("utf-8"))
        s = state.compute(project.find(root), 2)   # edited, never committed
        self.assertEqual(s.scripts[0].todos_done, 3)


class PartTests(Base):
    def two_parts(self):
        scripts = [moth(), script(2, "Orbit", ["2.1"], [])]
        parts = [{"name": "Part 1", "tasks": [], "scripts": [1]},
                 {"name": "Part 2", "tasks": [], "scripts": [2]}]
        return plan(scripts, parts)

    def test_turn_goes_back_to_ai_for_part_two(self):
        s = self.compute(self.two_parts(), left=[], stored=self.fresh(),
                         files={"src/Orbit.cs": shell(["2.1"])})
        self.assertEqual((s.turn, s.part), ("ai", 1))
        self.assertEqual(s.status, "build")
        self.assertEqual([x.status for x in s.scripts], ["done", "not started"])

    def test_turn_stays_with_the_owner_while_a_script_is_open(self):
        s = self.compute(self.two_parts(), left=["1.5"], files={"src/Orbit.cs": shell(["2.1"])})
        self.assertEqual((s.turn, s.part), ("owner", 0))

    def test_nothing_is_written(self):
        proj = self.make(self.two_parts(), left=[], stored=self.fresh())
        before = proj.state_path(2).read_bytes()
        state.compute(proj, 2)
        self.assertEqual(proj.state_path(2).read_bytes(), before)

    def test_a_part_whose_scripts_are_null(self):
        parts = [{"name": "Part 1", "tasks": [], "scripts": [1]}, {"name": "Part 2", "tasks": [], "scripts": None}]
        s = self.compute(plan([moth()], parts), left=[], stored=dict(self.fresh(), part=1))
        self.assertEqual((s.status, [x.status for x in s.scripts]), ("wrap-up", ["done"]))

    def test_a_script_in_no_part_blocks_tune_and_is_reachable(self):
        scripts = [moth(), script(2, "Orbit", ["2.1"], [])]
        plan_ = plan(scripts, [{"name": "Part 1", "tasks": [], "scripts": [1]}])
        s = self.compute(plan_, left=[], stored=self.fresh(), files={"src/Orbit.cs": shell(["2.1"])})
        self.assertEqual((s.status, s.next_todo, s.next_script), ("build", "2.1", 2))

    def test_empty_plan_stays_in_build_with_a_problem(self):
        s = self.compute({}, left=[])
        item = texts.plan_missing("phase-2.plan.json")
        self.assertEqual((s.status, s.problems, s.open_items), ("build", [item], [item]))

    def test_last_part_handed_over_and_done_is_not_back_to_ai(self):
        s = self.compute(plan([moth()]), left=[], stored=self.fresh())
        self.assertEqual(s.turn, "owner")

    def test_second_part_handed_over_counts_the_first_as_done(self):
        files = {"src/Orbit.cs": shell(["2.1"])}
        s = self.compute(self.two_parts(), left=[], stored=dict(self.fresh(), part=1), files=files)
        self.assertEqual([x.todos_done for x in s.scripts], [5, 0])


class StatusTests(Base):
    TARGETS = [{"id": "wins", "text": "Wins", "measure": "m", "settings": [], "min": 40, "max": 60},
               {"id": "time", "text": "Time", "measure": "m", "settings": [], "max": 90}]

    def done(self, log=None):
        stored = dict(self.fresh(), log=log or [])
        return self.compute(plan([moth()], targets=self.TARGETS), left=[], stored=stored)

    def test_all_done_is_tune(self):
        s = self.done()
        self.assertEqual((s.status, s.turn, s.targets_met, s.targets_total), ("tune", "owner", 0, 2))
        self.assertEqual([i for i in s.open_items if i not in s.wrap_items],
                         [texts.target_open("wins"), texts.target_open("time")])

    def test_targets_met_or_reason_is_wrap_up(self):
        s = self.done([{"kind": "measure", "target": "wins", "value": 30},
                       {"kind": "measure", "target": "wins", "value": 50},
                       {"kind": "reason", "target": "time", "text": "fun anyway"}])
        self.assertEqual((s.status, s.targets_met), ("wrap-up", 1))
        self.assertEqual(s.open_items, s.wrap_items)

    def test_one_sided_target_and_last_value_counts(self):
        s = self.done([{"kind": "measure", "target": "wins", "value": 60},
                       {"kind": "measure", "target": "time", "value": 91},
                       {"kind": "measure", "target": "time", "value": 90}])
        self.assertEqual((s.status, s.targets_met), ("wrap-up", 2))

    def test_missed_target_without_reason_stays_tune(self):
        s = self.done([{"kind": "measure", "target": "wins", "value": 50},
                       {"kind": "measure", "target": "time", "value": 100}])
        self.assertEqual((s.status, s.targets_met), ("tune", 1))

    def test_no_targets_is_met(self):
        s = self.compute(plan([moth()]), left=[], stored=self.fresh())
        self.assertEqual(s.status, "wrap-up")

    def test_owner_marks_and_suites_are_open_after_build(self):
        files = {"src/MothTests.cs": '[Explicit("Owner")]\n'}
        s = self.compute(plan([moth()]), left=[], stored=self.fresh(), files=files)
        self.assertTrue(any("src/MothTests.cs:1" in i for i in s.open_items))
        s = self.compute(plan([script(1, "Moth", ALL, [])]), left=[])
        self.assertIn(texts.suite_not_recorded("Unit"), s.open_items)

    def test_stored_statuses_stay(self):
        for stored in ("planning", "done", "skipped"):
            s = self.compute(plan([moth()]), stored={"status": stored})
            self.assertEqual((s.status, s.scripts, s.wrong_branch), (stored, [], None))

    def test_wrong_branch(self):
        with mock.patch.object(state, "current_branch", return_value="main"):
            s = self.compute(plan([moth()]))
        self.assertEqual(s.wrong_branch, "main")
        with mock.patch.object(state, "current_branch", return_value=state.DETACHED):
            self.assertEqual(self.compute(plan([moth()])).wrong_branch, state.DETACHED)

    def test_no_branch_check_without_git_or_branch_or_in_planning(self):
        with mock.patch.object(state, "current_branch", return_value=None):
            self.assertIsNone(self.compute(plan([moth()])).wrong_branch)
        with mock.patch.object(state, "current_branch", return_value="main"):
            self.assertIsNone(self.compute(plan([moth()]), stored={"branch": None}).wrong_branch)
            self.assertIsNone(self.compute(plan([moth()]), stored={"status": "planning"}).wrong_branch)
            tuned = self.compute(plan([moth()]), left=[], stored=self.fresh())
            self.assertEqual(tuned.wrong_branch, "main")

    def test_a_project_without_settings_does_not_crash(self):
        proj = project.Project(self.tmp, {})
        helpers.write_json(proj.state_path(2), {"status": "build"})
        s = state.compute(proj, 2)
        self.assertEqual(s.status, "build")


class OpenItemTests(Base):
    """open_items holds everything /finish-phase checks, in every state of a build."""

    def test_parts_not_handed_over_and_wrap_up_are_listed_while_building(self):
        s = self.compute(plan([moth()]), stored={"turn": "ai"})
        for item in (texts.part_not_handed(0, "Part 1"), texts.todos_left("Owner 1 Moth", 5),
                     texts.suite_not_recorded("Unit"), texts.summary_missing("Enemy AI"),
                     texts.lessons_count(0), texts.SURPRISED_MISSING, texts.DIFFERENTLY_MISSING):
            self.assertIn(item, s.open_items)

    def test_todo_of_a_script_in_another_file(self):
        files = {"src/Other.cs": "x\n" + shell(["1.3", "7.1"])}
        s = self.compute(plan([moth()]), files=files)
        self.assertIn(texts.todo_elsewhere("1.3", "src/Other.cs"), s.open_items)
        self.assertFalse(any("7.1" in i for i in s.open_items))
        self.assertFalse(any("src/Moth.cs" in i for i in s.open_items))   # counted once, by its label

    def test_rating_and_answers(self):
        p = dict(plan([moth()]), questions=[{"id": "q1", "concept": "ai", "text": "?", "points": ["x"]}])
        s = self.compute(p, stored={"log": [{"kind": "rating", "concept": "ai", "rating": "on my own"},
                                            {"kind": "rating", "concept": "ai", "rating": "can't yet"}]})
        self.assertIn(texts.rating_missing("Enemy AI"), s.open_items)
        self.assertIn(texts.answer_missing("Enemy AI"), s.open_items)
        helpers.make_project(self.tmp, phases={2: {"md": helpers.FULL_MD}})
        data = {"status": "build", "branch": "stage-2", "turn": "owner", "part": 0,
                "log": [{"kind": "rating", "concept": "ai", "rating": "with help"}]}
        helpers.write_json(self.project.state_path(2), data)
        self.assertEqual(state.compute(self.project, 2).wrap_items, [])

    def test_changed_plan_is_a_problem(self):
        s = self.compute(plan([moth()]), stored={"planHash": "0" * 64})
        item = texts.plan_changed(2, "phase-2.plan.json")
        self.assertTrue(s.plan_changed)
        self.assertIn(item, s.problems)
        self.assertIn(item, s.open_items)

    def test_planning_is_open(self):
        s = self.compute(plan([moth()]), stored={"status": "planning"})
        self.assertEqual(s.open_items, [texts.plan_not_approved(2)])


class GitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.git = ["git", "-C", str(self.tmp), "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
        try:
            subprocess.run(self.git + ["init", "-q"], check=True, capture_output=True)
            subprocess.run(self.git + ["commit", "-q", "--allow-empty", "-m", "x"], check=True, capture_output=True)
        except (OSError, subprocess.CalledProcessError):
            self.skipTest("git is not available")
        self.project = project.Project(self.tmp, {})

    def run_git(self, *args):
        subprocess.run(self.git + list(args), check=True, capture_output=True)

    def test_current_branch_and_detached(self):
        self.run_git("switch", "-q", "-c", "stage-2")
        self.assertEqual(state.current_branch(self.project), "stage-2")
        self.run_git("checkout", "-q", "--detach")
        self.assertEqual(state.current_branch(self.project), state.DETACHED)

    def test_no_repository_is_none(self):
        other = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, other, True)
        with mock.patch.dict("os.environ", {"GIT_CEILING_DIRECTORIES": str(other.parent)}):
            self.assertIsNone(state.current_branch(project.Project(other, {})))
            self.assertTrue(state.is_merged(project.Project(other, {}), "stage-2"))

    def test_is_merged(self):
        self.run_git("switch", "-q", "-c", "stage-2")
        self.run_git("commit", "-q", "--allow-empty", "-m", "work")
        self.run_git("switch", "-q", "-")
        self.assertFalse(state.is_merged(self.project, "stage-2"))
        self.run_git("merge", "-q", "--ff-only", "stage-2")
        self.assertTrue(state.is_merged(self.project, "stage-2"))
        self.assertTrue(state.is_merged(self.project, "never-existed"))

    def two_branches(self, main="main"):
        """`main` with one commit, and stage-2 (checked out) with one more."""
        self.run_git("branch", "-q", "-M", main)
        self.run_git("switch", "-q", "-c", "stage-2")
        self.run_git("commit", "-q", "--allow-empty", "-m", "work")

    def test_is_merged_while_the_branch_is_checked_out(self):
        for main in ("main", "master"):
            self.two_branches(main)
            self.assertFalse(state.is_merged(self.project, "stage-2"), main)
            self.run_git("branch", "-f", main, "stage-2")
            self.assertTrue(state.is_merged(self.project, "stage-2"), main)
            self.run_git("switch", "-q", main)
            self.assertTrue(state.is_merged(self.project, main))
            self.run_git("branch", "-D", "stage-2")

    def test_is_merged_prefers_main_over_master(self):
        self.two_branches("main")
        self.run_git("branch", "master", "stage-2")
        self.assertFalse(state.is_merged(self.project, "stage-2"))

    def test_is_merged_with_origin_head(self):
        self.two_branches("trunk")
        self.run_git("update-ref", "refs/remotes/origin/trunk", "trunk")
        self.run_git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/trunk")
        self.run_git("branch", "main", "stage-2")   # origin/HEAD decides, not the name main
        self.assertFalse(state.is_merged(self.project, "stage-2"))
        self.run_git("update-ref", "refs/remotes/origin/trunk", "stage-2")   # merged on the server
        self.assertTrue(state.is_merged(self.project, "stage-2"))

    def test_is_merged_into_the_local_main_of_origin_head(self):
        self.two_branches("trunk")
        self.run_git("update-ref", "refs/remotes/origin/trunk", "trunk")
        self.run_git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/trunk")
        self.run_git("branch", "-f", "trunk", "stage-2")
        self.assertTrue(state.is_merged(self.project, "stage-2"))

    def test_a_dangling_origin_head_falls_back_to_main(self):
        self.two_branches("main")
        self.run_git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/gone")
        self.assertFalse(state.is_merged(self.project, "stage-2"))

    def test_is_merged_without_a_main_branch(self):
        self.two_branches("other")
        self.assertTrue(state.is_merged(self.project, "stage-2"))

    def test_no_git_program_is_none(self):
        with mock.patch("subprocess.run", side_effect=FileNotFoundError):
            self.assertIsNone(state.current_branch(self.project))
            self.assertTrue(state.is_merged(self.project, "stage-2"))


if __name__ == "__main__":
    unittest.main()
