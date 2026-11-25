import json
import os
import shutil
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import helpers
from helpers import FULL_MD, OLD, TEST_CODE, TWO_PARTS, full_plan, shell, suite_result
from gl import commands, project, render, results, state, store, texts, version


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.branch = "stage-2"
        self.merged = True
        for name, fn in (("current_branch", lambda p: self.branch), ("is_merged", lambda p, b: self.merged)):
            patcher = mock.patch.object(state, name, side_effect=fn)
            patcher.start()
            self.addCleanup(patcher.stop)

    def make(self, phases=None, files=None, settings=None):
        root = helpers.make_project(self.tmp, phases=phases, files=files, settings=settings)
        self.project = project.find(root)
        return self.project

    def run_(self, name, argument=""):
        out = commands.run(self.project, name, argument)
        self.assertRegex(out.text.splitlines()[-1], r"^Next: .*/[a-z]+-phase")
        return out

    def refused(self, name, argument=""):
        before = self.snapshot()
        out = self.run_(name, argument)
        self.assertFalse(out.ok, out.text)
        self.assertEqual(self.snapshot(), before, "a refusal writes nothing")
        return out.text

    def accepted(self, name, argument=""):
        out = self.run_(name, argument)
        self.assertTrue(out.ok, out.text)
        return out.text

    def snapshot(self):
        return {str(f): f.read_bytes() for f in self.tmp.rglob("*") if f.is_file()}

    def data(self, n=2):
        return store.read(self.project.state_path(n))

    def put_plan(self, plan_, n=2):
        helpers.write_json(self.project.plan_path(n), plan_)


class StartTests(Base):
    def test_first_phase_has_no_check(self):
        self.make()
        text = self.accepted("start", "1")
        self.assertEqual(self.data(1)["status"], "planning")
        self.assertIn("Docs/learning/phase-1.plan.json", text)
        self.assertTrue(text.endswith(texts.next_line("approve-phase", 1)))

    def test_long_command_name_works_too(self):
        self.make()
        self.accepted("start-phase", "1")

    def test_blocked_while_previous_is_open(self):
        proj = self.make({1: {"state": {"status": "build", "turn": "owner", "part": 0}, "plan": full_plan(1)}},
                         files={"src/Moth.cs": shell(["1.2"])})
        text = self.refused("start", "2")
        items = state.compute(proj, 1).open_items
        self.assertGreater(len(items), 5)
        for item in items:
            self.assertIn(item, text)
        self.assertTrue(text.endswith(texts.next_line("summarize-phase", 1)))

    def test_blocked_while_previous_is_planned(self):
        self.make({1: {"state": {"status": "planning"}}})
        text = self.refused("start", "2")
        self.assertIn(texts.plan_not_approved(1), text)
        self.assertTrue(text.endswith(texts.next_line("start-phase", 1)))   # the plan is not finished
        self.put_plan(full_plan(1), 1)
        self.assertTrue(self.refused("start", "2").endswith(texts.next_line("approve-phase", 1)))

    def test_skip_needs_a_reason(self):
        self.make({1: {"state": {"status": "planning"}}})
        for argument in ("2 skip:", "2 skip:   ", "2 skip"):
            self.assertIn("skip: <reason>", self.refused("start", argument))

    def test_skip_carries_open_items(self):
        proj = self.make({1: {"state": {"status": "build", "turn": "owner", "part": 0}, "plan": full_plan(1)}},
                         files={"src/Moth.cs": shell(["1.2"])})
        items = state.compute(proj, 1).open_items
        text = self.accepted("start", "2   Skip: no time: really")
        self.assertEqual((self.data(1)["status"], self.data(1)["skip"]), ("skipped", "no time: really"))
        self.assertEqual(self.data(2)["carried"], items)
        self.assertIn(items[0], text)
        self.assertTrue(text.startswith(texts.skipped_text(1, "no time: really") + "\n"))

    def test_skip_of_a_phase_without_a_file_creates_it(self):
        self.make()
        self.accepted("start", "2 skip: started elsewhere")
        self.assertEqual(self.data(1), {"status": "skipped", "skip": "started elsewhere"})
        self.assertEqual(self.data(2)["status"], "planning")

    def test_done_but_not_merged_is_blocked(self):
        self.make({1: {"state": {"status": "done", "branch": "stage-1"}, "plan": full_plan(1)}})
        self.merged = False
        text = self.refused("start", "2")
        self.assertIn("merge", text.lower())
        self.assertIn("stage-1", text)
        self.assertNotIn("was skipped", self.accepted("start", "2 skip: merge comes later"))
        self.assertEqual(self.data(1)["status"], "done")
        self.assertNotIn("skip", self.data(1))

    def test_skipped_previous_is_enough(self):
        self.make({1: {"state": {"status": "skipped", "skip": "x"}}})
        self.accepted("start", "2")

    def test_done_previous_carries_weak_concepts_and_differently(self):
        log = [{"kind": "rating", "concept": "ai", "rating": "with help"}]
        self.make({1: {"state": {"status": "done", "log": log}, "plan": full_plan(1), "md": FULL_MD}})
        self.accepted("start", "2")
        self.assertEqual(self.data(2)["carried"],
                         [texts.carried_concept("Enemy AI"), texts.carried_differently("start smaller")])

    def test_creates_the_three_files(self):
        proj = self.make()
        self.accepted("start", "1")
        self.assertEqual(store.read(proj.plan_path(1)),
                         {"phase": 1, "concepts": [], "parts": [], "scripts": [], "targets": [], "questions": []})
        md = proj.md_path(1).read_bytes()
        self.assertNotIn(b"\r", md)
        for heading in ("# Phase 1", "## Notes for later", "## Answers", "## Concept summary", "## Lessons",
                        "## Process", "Surprised me:", "Differently:"):
            self.assertIn(heading, md.decode("utf-8").splitlines())

    def test_existing_files_are_not_overwritten(self):
        proj = self.make({1: {"plan": full_plan(1), "md": FULL_MD}})
        before = self.snapshot()
        self.accepted("start", "1")
        after = self.snapshot()
        for path in (proj.plan_path(1), proj.md_path(1)):
            self.assertEqual(after[str(path)], before[str(path)])

    def test_missing_previous_file_is_blocked_and_says_skip(self):
        self.make()
        self.assertIn("/start-phase 2 skip: <reason>", self.refused("start", "2"))

    def test_started_already(self):
        self.make({1: {"state": {"status": "planning"}}})
        before = self.snapshot()
        text = self.accepted("start", "1")
        self.assertIn("phase-1.plan.json", text)
        self.assertTrue(text.endswith(texts.next_line("approve-phase", 1)))
        self.assertEqual(self.snapshot(), before)
        self.make({1: {"state": {"status": "build", "turn": "ai"}, "plan": full_plan(1)}})
        self.assertTrue(self.refused("start", "1").endswith(texts.next_line("build-phase", 1)))
        self.make({1: {"state": {"status": "done"}}})
        self.assertTrue(self.refused("start", "1").endswith(texts.next_line("start-phase", 2)))

    def test_a_skipped_phase_can_be_planned_again(self):
        self.make({1: {"state": {"status": "skipped", "skip": "x", "turn": "owner", "part": 1, "planHash": "h",
                                 "reached": "tune", "workHash": "w",
                                 "locked": ["src/Moth.cs"], "handed": {"1": {}}, "branch": "b", "carried": ["old"],
                                 "log": [{"kind": "note"}]}}})
        self.accepted("start", "1")
        self.assertEqual(self.data(1), {"status": "planning", "carried": ["old"], "log": [{"kind": "note"}]})

    def test_bad_arguments(self):
        self.make({1: {"state": {"status": "skipped"}}})
        for argument in ("", "abc", "0", "-1", "2.5", "2 hello", "phase-x", "2x"):
            self.refused("start", argument)

    def test_rehearsal_works_on_the_fake_project(self):
        root = helpers.make_project(self.tmp)
        helpers.make_project(root / ".claude" / "learning" / "rehearsal")
        helpers.set_switch(root, '{"rehearsal": true}')
        self.project = project.find(root)
        self.accepted("start", "1")
        self.assertFalse(self.project.state_path(1).exists())
        self.assertTrue(self.project.active.state_path(1).exists())

    def test_two_starts_at_once_keep_the_carried_items(self):
        self.make({1: {"state": {"status": "build", "turn": "owner", "part": 0}, "plan": full_plan(1)}})
        outs = []
        threads = [threading.Thread(target=lambda i=i: outs.append(
            commands.run(self.project, "start", "2 skip: reason %d" % i))) for i in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual([o.ok for o in outs], [True] * 6)
        self.assertTrue(self.data(2)["carried"])


class StartOnGitTests(unittest.TestCase):
    """The merge check on a real repository, with the branch still checked out and with another one."""

    def test_done_but_not_merged_is_blocked(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        root = helpers.make_project(tmp, phases={1: {"state": {"status": "done", "branch": "stage-1"}}})
        git = ["git", "-C", str(tmp), "-c", "user.name=t", "-c", "user.email=t@example.invalid"]

        def run(*args):
            subprocess.run(git + list(args), check=True, capture_output=True)

        try:
            run("init", "-q")
            run("commit", "-q", "--allow-empty", "-m", "x")
            run("branch", "-q", "-M", "main")
        except (OSError, subprocess.CalledProcessError):
            self.skipTest("git is not available")
        run("switch", "-q", "-c", "stage-1")
        run("commit", "-q", "--allow-empty", "-m", "work")
        proj = project.find(root)
        for branch in ("stage-1", "main"):   # still on the unmerged branch; switched away from it
            run("switch", "-q", branch)
            out = commands.run(proj, "start", "2")
            self.assertFalse(out.ok, branch)
            self.assertIn("Merge", out.text)
        run("merge", "-q", "--ff-only", "stage-1")
        self.assertTrue(commands.run(proj, "start", "2").ok)


class GitBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def make(self, phases=None, files=None):
        root = helpers.make_project(self.tmp / "game", phases=phases, files=files)
        if not helpers.git_init(root):
            self.skipTest("git is not available")
        self.project = project.find(root)
        return self.project

    def git(self, *args):
        return helpers.git(self.project.root, *args)

    def commit(self):
        helpers.commit(self.project.root)

    def refused(self, name, argument=""):
        out = commands.run(self.project, name, argument)
        self.assertFalse(out.ok, out.text)
        return out.text

    def accepted(self, name, argument=""):
        out = commands.run(self.project, name, argument)
        self.assertTrue(out.ok, out.text)
        return out.text


class UncommittedTests(GitBase):
    """The phase files of the phase before, changed and not committed."""

    ITEM = texts.phase_files_uncommitted(1, ["Docs/learning/phase-1.json", "Docs/learning/phase-1.md"])

    def change(self, **more):
        self.project.update_state(1, lambda d: d.update(more))
        self.project.md_path(1).write_bytes(b"# Phase 1\n")

    def test_done_and_not_merged(self):
        self.make({1: {"state": {"status": "build", "branch": "stage-1", "turn": "ai"}, "plan": full_plan(1)}})
        self.git("switch", "-q", "-c", "stage-1")
        self.git("commit", "-q", "--allow-empty", "-m", "work")
        self.change(status="done")
        text = self.refused("start", "2")
        self.assertIn(self.ITEM, text)
        self.assertIn("Commit them first", text)
        self.commit()
        text = self.refused("start", "2")
        self.assertNotIn("ommit them first", text)
        self.assertIn(texts.previous_not_merged(2, "stage-1"), text)

    def test_still_open(self):
        self.make({1: {"state": {"status": "build", "turn": "ai"}, "plan": full_plan(1)}})
        self.assertNotIn("ommit them first", self.refused("start", "2"))
        self.change(x=1)
        self.assertIn(self.ITEM, self.refused("start", "2"))

    def test_without_git_and_in_a_rehearsal_nothing_is_said(self):
        self.make({1: {"state": {"status": "build", "turn": "ai"}, "plan": full_plan(1)}})
        self.change(x=1)
        with mock.patch.object(state, "_git", return_value=None):
            self.assertNotIn("ommit them first", self.refused("start", "2"))
        self.assertEqual(state.uncommitted(project.Project(self.project.rehearsal_folder, {"docs": "d"}), 1), [])


class OtherBranchTests(GitBase):
    """An open phase while its files are not on the branch that is checked out."""

    SHELLS = {"src/Moth.cs": shell(["1.1", "1.2"]), "src/Lamp.cs": shell(["2.1"]), "src/Keeper.cs": shell(["3.1"])}
    WRONG = texts.wrong_branch("stage-2", "main")

    def record(self):
        return store.read(self.project.root / ".claude" / "learning" / "local" / "open.json")

    def entry(self, branch="stage-2", locked=(), built=True):
        return {"2": {"branch": branch, "locked": list(locked), "built": built}}

    def planned(self):
        """Phase 1 is done; phase 2 is planned and nothing of it is committed."""
        self.make({1: {"state": {"status": "done"}, "plan": full_plan(1)}})
        self.accepted("start", "2")
        helpers.write_json(self.project.plan_path(2), full_plan())

    def build(self):
        self.accepted("approve", "2")
        self.accepted("build", "2")

    def away(self, hand_over=True):
        """Phase 2 is built on stage-2, and main is checked out."""
        self.make({1: {"state": {"status": "done"}, "plan": full_plan(1)}})
        self.git("switch", "-q", "-c", "stage-2")
        self.accepted("start", "2")
        helpers.write_json(self.project.plan_path(2), full_plan())
        self.build()
        if hand_over:
            helpers.make_project(self.project.root, files=dict(self.SHELLS, **TEST_CODE))
            tests = {t: "failed" for s in full_plan()["scripts"] for t in s["tests"]}
            self.project.update_state(2, lambda d: d.update(results={"Unit": suite_result(tests)}))
            out = commands.hand_over(self.project, 2)
            self.assertTrue(out.ok, out.text)
        self.commit()
        self.git("switch", "-q", "main")
        self.assertFalse(self.project.state_path(2).exists())

    def test_the_record_follows_the_phase(self):
        self.planned()
        self.git("switch", "-q", "-c", "stage-2")
        self.assertEqual(self.record(), {})
        self.accepted("approve", "2")
        self.assertEqual(self.record(), self.entry(built=False))
        self.git("switch", "-q", "-c", "other")
        self.accepted("build", "2")
        self.assertEqual(self.record(), self.entry("other"))
        self.project.update_state(2, lambda d: d.update(turn="owner", locked=["src/Moth.cs"]))
        self.accepted("start", "3 skip: later")
        self.assertEqual(self.record(), {})
        self.accepted("start", "2")   # planned again
        self.assertEqual(self.record(), {})

    def test_the_hand_over_notes_the_locks_and_finish_keeps_the_branch(self):
        self.away()
        self.assertEqual(self.record(), self.entry(locked=["src/Moth.cs", "src/Lamp.cs", "src/Keeper.cs"]))
        self.git("switch", "-q", "stage-2")
        for name in self.SHELLS:
            (self.project.root / name).write_bytes(b"class X {}\n")
        self.project.md_path(2).write_bytes(FULL_MD.encode("utf-8"))
        passed = {t: "passed" for s in full_plan()["scripts"] for t in s["tests"]}
        self.project.update_state(2, lambda d: d.update(results={"Unit": suite_result(passed)}, log=FinishTests.LOG))
        self.accepted("finish", "2")
        self.assertEqual(self.record(), {"2": {"branch": "stage-2", "done": True, "locked": []}})

    def test_planning_again_removes_a_record_that_was_left(self):
        self.planned()
        self.project.update_local("open.json", lambda d: self.entry())
        self.project.update_state(2, lambda d: d.update(status="skipped"))
        self.accepted("start", "2")
        self.assertEqual(self.record(), {})

    def test_every_command_names_the_branch(self):
        self.away()
        before = self.git("status", "--porcelain")
        for argument in ("2", ""):
            text = self.accepted("summarize", argument)
            self.assertIn(self.WRONG, text)
            self.assertTrue(text.startswith("Phase 2 - build"), text)
            self.assertTrue(text.endswith(texts.next_line("summarize-phase", 2)))
        for name, argument in (("build", "2"), ("build", ""), ("approve", "2"), ("approve", "2 change: x"),
                               ("finish", "2"), ("start", "2"), ("start", "3"), ("start", "3 skip: x"), ("start", "4")):
            text = self.refused(name, argument)
            self.assertIn(self.WRONG, text, name)
            self.assertTrue(text.endswith(texts.next_line("summarize-phase", 2)), text)
        out = commands.hand_over(self.project, None)
        self.assertEqual((out.ok, self.WRONG in out.text), (False, True), out.text)
        self.assertEqual(self.git("status", "--porcelain"), before)
        self.assertIn("Phase 1 - done", self.accepted("summarize", "1"))
        self.git("switch", "-q", "--detach", "main")
        self.assertIn(texts.wrong_branch("stage-2", state.DETACHED), self.accepted("summarize", "2"))
        self.git("switch", "-q", "stage-2")
        self.assertIn("Your turn", self.accepted("summarize", "2"))

    def test_an_older_phase_file_counts_as_missing(self):
        self.planned()
        self.commit()   # planned on main, and built on stage-2
        self.git("switch", "-q", "-c", "stage-2")
        self.build()
        self.commit()
        self.git("switch", "-q", "main")
        self.assertEqual(self.project.active and store.read(self.project.state_path(2))["status"], "planning")
        self.assertIn(self.WRONG, self.accepted("summarize", "2"))
        for name, argument in (("start", "2"), ("start", "3"), ("approve", "2"), ("build", "2"), ("finish", "2")):
            self.assertIn(self.WRONG, self.refused(name, argument))

    def test_approved_here_and_built_elsewhere(self):
        self.planned()
        self.accepted("approve", "2")
        self.commit()
        self.git("switch", "-q", "-c", "stage-2")   # after the approval: not wrong
        self.assertNotIn("Wrong branch", self.accepted("summarize", "2"))
        self.accepted("build", "2")
        self.commit()
        self.git("switch", "-q", "main")
        self.assertIn(self.WRONG, self.refused("build", "2"))

    def test_a_done_phase_here_is_not_away(self):
        self.away()
        for status in ("done", "skipped"):
            helpers.write_json(self.project.state_path(2), {"status": status})
            self.assertNotIn("Wrong branch", self.accepted("summarize", "2"))

    def test_without_git_or_branch_or_record_it_is_as_before(self):
        self.away()
        as_before = texts.no_phase(2, [1])
        with mock.patch.object(state, "_git", return_value=None):
            self.assertIn(as_before, self.refused("summarize", "2"))
        local = self.project.root / ".claude" / "learning" / "local" / "open.json"
        for raw in (b"{", b"[]", b'{"2": 5, "x": {}}', b'{"2": {"branch": 5, "locked": 7}}'):
            local.write_bytes(raw)
            self.assertIn(as_before, self.refused("summarize", "2"), raw)
        helpers.write_json(local, self.entry())
        self.assertIn(self.WRONG, self.accepted("summarize", "2"))
        self.git("branch", "-m", "stage-2", "renamed")
        self.assertIn(as_before, self.refused("summarize", "2"))

    def test_a_damaged_record_is_replaced(self):
        self.planned()
        local = self.project.root / ".claude" / "learning" / "local"
        local.mkdir(parents=True, exist_ok=True)
        (local / "open.json").write_bytes(b"{")
        self.accepted("approve", "2")
        self.assertEqual(self.record(), self.entry("main", built=False))

    def test_a_record_that_cannot_be_written_does_not_undo_the_command(self):
        self.planned()
        with mock.patch.object(project.Project, "update_local", side_effect=store.LockTimeout("x")):
            self.accepted("approve", "2")
        self.assertEqual(store.read(self.project.state_path(2))["status"], "build")

    def test_a_rehearsal_has_no_record(self):
        self.away()
        fake = project.Project(self.project.rehearsal_folder, self.project.settings)
        fake.note_open(2, {"status": "build", "branch": "stage-2", "turn": "ai"})
        self.assertFalse((fake.root / ".claude" / "learning" / "local").exists())
        helpers.write_json(fake.root / ".claude" / "learning" / "local" / "open.json", self.entry())
        self.assertEqual(fake.open_phases(), {})


class ApproveTests(Base):
    def planning(self, plan_=None, stored=None):
        st = {"status": "planning"}
        st.update(stored or {})
        return self.make({2: {"state": st, "plan": full_plan() if plan_ is None else plan_}})

    def gaps(self, plan_):
        self.planning(plan_)
        return self.refused("approve", "2")

    def test_incomplete_plan_lists_every_gap(self):
        p = full_plan()
        p["scripts"][0]["tests"] = []
        p["scripts"][1].pop("tests")
        p["targets"][0].pop("min")
        p["targets"][0].pop("max")
        p["concepts"].append({"id": "light", "name": "Light"})
        text = self.gaps(p)
        for item in (texts.gap_script("Owner 1 Moth", "tests"), texts.gap_script("Owner 2 Lamp", "tests"),
                     texts.gap_target_range("wins"), texts.gap_question("Light")):
            self.assertIn(item, text)
        self.assertTrue(text.endswith(texts.next_line("start-phase", 2)))
        p["concepts"] = []
        self.assertIn(texts.GAP_NO_CONCEPT, self.gaps(p))

    def test_an_empty_plan_and_a_missing_one(self):
        proj = self.planning({"phase": 2})
        text = self.refused("approve", "2")
        for item in (texts.GAP_NO_CONCEPT, texts.gap_script_count(0), texts.GAP_NO_TARGET, texts.GAP_NO_PART):
            self.assertIn(item, text)
        proj.plan_path(2).unlink()
        self.assertIn(texts.GAP_NO_CONCEPT, self.refused("approve", "2"))

    def test_each_gap(self):
        def change(fn):
            p = full_plan()
            fn(p)
            return self.gaps(p)

        s, t, q = "scripts", "targets", "questions"
        cases = [
            (lambda p: p[s][0].update(path=""), texts.gap_script("Owner 1 Moth", "path")),
            (lambda p: p[s][0].update(concept=""), texts.gap_script("Owner 1 Moth", "concept")),
            (lambda p: p[s][0].update(todos=[]), texts.gap_script("Owner 1 Moth", "todos")),
            (lambda p: p[s][0].update(tests="MothTests.Turns"), texts.gap_script("Owner 1 Moth", "tests")),
            (lambda p: p[s][0].update(concept="sound"), texts.gap_unknown_concept("Owner 1 Moth", "sound")),
            (lambda p: p["parts"][0].update(scripts=[1, 2]), texts.gap_parts("Owner 3 Keeper", 0)),
            (lambda p: p["parts"].append({"name": "B", "tasks": ["x"], "scripts": [3]}),
             texts.gap_parts("Owner 3 Keeper", 2)),
            (lambda p: p["parts"][0].update(scripts=[1, 2, 3, 9]), texts.gap_part_script("Part 1", 9)),
            (lambda p: p["parts"][0].update(tasks=[]), texts.gap_part_tasks("Part 1")),
            (lambda p: p.update(parts=[]), texts.GAP_NO_PART),
            (lambda p: p[s][1].update(id=1), texts.gap_duplicate("scripts", 1)),
            (lambda p: p["concepts"].append({"id": "ai", "name": "B"}), texts.gap_duplicate("concepts", "ai")),
            (lambda p: p[q].append(dict(p[q][0])), texts.gap_duplicate("questions", "q1")),
            (lambda p: p[t].append(dict(p[t][0])), texts.gap_duplicate("targets", "wins")),
            (lambda p: p[s][0].update(todos=["1.1", "2.2"]), texts.gap_todo("Owner 1 Moth", "2.2")),
            (lambda p: p[s][0].update(todos=["1.1", "1.x"]), texts.gap_todo("Owner 1 Moth", "1.x")),
            (lambda p: p[s][0].update(todos=["1.1", "1.1"]), texts.gap_duplicate("TODOs", "1.1")),
            (lambda p: p.update(targets=[]), texts.GAP_NO_TARGET),
            (lambda p: p[t][0].update(measure=" "), texts.gap_target("wins", "measure")),
            (lambda p: p[t][0].update(settings=[]), texts.gap_target("wins", "settings")),
            (lambda p: p[t][0].update(min="40"), texts.gap_target_range("wins")),
            (lambda p: p[t][0].update(min=True), texts.gap_target_range("wins")),
            (lambda p: p[t][0].update(min=70), texts.gap_target_range("wins")),
            (lambda p: p.update(questions=[]), texts.gap_question("Enemy AI")),
            (lambda p: p[q][0].update(points=[]), texts.gap_points("q1")),
            (lambda p: p.update(scripts={"a": 1}), texts.gap_list("scripts")),
            (lambda p: p.update(concepts=["ai"]), texts.gap_list("concepts")),
            (lambda p: p["parts"][0].update(scripts=1), texts.gap_parts("Owner 1 Moth", 0)),
            (lambda p: p[s][0].pop("id"), texts.gap_id("scripts")),
            (lambda p: p[s][0].update(id="moth", todos=["moth.1"]), texts.gap_script_id("moth")),
            (lambda p: p[s][0].update(id=True, todos=["True.1"]), texts.gap_script_id("True")),
            (lambda p: p[s][0].update(todos=[1.1]), texts.gap_script("Owner 1 Moth", "todos")),
            (lambda p: p[s][0].update(tests=[None]), texts.gap_script("Owner 1 Moth", "tests")),
            (lambda p: p[s][0].update(tests=["MothTests.Turns", " "]), texts.gap_script("Owner 1 Moth", "tests")),
            (lambda p: p["parts"][0].update(tasks=[None]), texts.gap_part_tasks("Part 1")),
            (lambda p: p["parts"][0].update(scripts=None), texts.gap_part_scripts("Part 1")),
            (lambda p: p["parts"].append({"name": "B", "tasks": ["x"], "scripts": None}),
             texts.gap_part_scripts("Part 2 (B)")),
            (lambda p: p["parts"][0].update(scripts=[1, 2, 3, None]), texts.gap_part_script("Part 1", None)),
            (lambda p: p[t][0].update(settings=[5]), texts.gap_target("wins", "settings")),
            (lambda p: p[q][0].update(points=[""]), texts.gap_points("q1")),
            (lambda p: p["concepts"][0].update(name=" "), texts.gap_concept_name("ai")),
        ] + [(lambda p, path=path: p[s][0].update(path=path), texts.gap_script_path("Owner 1 Moth", path, ["src"], [".cs"]))
             for path in ("Assets/Moth.cs", "C:/game/src/Moth.cs", "C:Moth.cs", "/src/Moth.cs", "\\src\\Moth.cs",
                          "src/../src/Moth.cs", "src\\..\\src\\Moth.cs", "src/Moth.txt", "src/Moth", "src",
                          str(self.tmp / "src" / "Moth.cs"))] + [
            (lambda p: p["concepts"][0].pop("name"), texts.gap_concept_name("ai")),
        ]
        for fn, item in cases:
            self.assertIn(item, change(fn))

    def test_paths_in_a_code_folder_are_fine(self):
        p = full_plan()
        p["scripts"][0]["path"] = "src/Enemies/Moth.CS"
        p["scripts"][1]["path"] = "src/La..mp.cs"
        self.planning(p)
        self.accepted("approve", "2")

    def test_one_sided_target_and_empty_part_are_fine(self):
        p = full_plan(parts=TWO_PARTS + [{"name": "Rest", "tasks": ["Sound"], "scripts": []},
                                         {"name": "More", "tasks": ["Music"]}])
        p["targets"][0].pop("max")
        self.planning(p)
        self.accepted("approve", "2")

    def test_locks_the_hash(self):
        proj = self.planning()
        text = self.accepted("approve", "2")
        d = self.data()
        self.assertEqual((d["status"], d["branch"]), ("build", "stage-2"))
        self.assertEqual(d["planHash"], store.file_hash(proj.plan_path(2)))
        self.assertNotIn("turn", d)
        self.assertTrue(text.endswith(texts.next_line("build-phase", 2)))

    def test_detached_head_stores_no_branch(self):
        self.branch = state.DETACHED
        self.planning()
        self.accepted("approve", "2")
        self.assertIsNone(self.data()["branch"])

    def test_changed_plan_is_reported_until_approved(self):
        proj = self.planning()
        self.accepted("approve", "2")
        self.accepted("build", "2")
        p = full_plan()
        p["targets"][0]["max"] = 70
        self.put_plan(p)
        item = texts.plan_changed(2, "phase-2.plan.json")
        self.assertIn(item, self.refused("approve", "2"))
        self.assertIn(item, self.accepted("summarize", "2"))
        self.assertIn(item, self.accepted("build", "2"))
        self.assertIn(item, self.refused("finish", "2"))
        self.accepted("approve", "2 change: the range was too narrow")
        self.assertEqual(self.data()["planHash"], store.file_hash(proj.plan_path(2)))
        for name in ("summarize", "build"):
            self.assertNotIn(item, self.accepted(name, "2"))

    def test_change_needs_a_reason_and_is_recorded(self):
        proj = self.planning()
        self.accepted("approve", "2")
        old = self.data()["planHash"]
        p = full_plan()
        p["targets"][0]["max"] = 70
        self.put_plan(p)
        self.assertIn("change: <reason>", self.refused("approve", "2 change:"))
        self.accepted("approve", "2 change: wider: yes")
        entry = self.data()["changes"][0]
        self.assertEqual((entry["reason"], entry["from"], entry["to"]),
                         ("wider: yes", old, store.file_hash(proj.plan_path(2))))
        self.assertTrue(entry["time"])
        self.assertEqual(self.data()["status"], "build")

    def test_a_changed_plan_is_checked_again(self):
        self.planning()
        self.accepted("approve", "2")
        self.put_plan(dict(full_plan(), targets=[]))
        text = self.refused("approve", "2 change: none")
        self.assertIn(texts.GAP_NO_TARGET, text)
        self.assertTrue(text.endswith(texts.next_line("approve-phase", 2)))   # it is planned already

    HANDED = {"1": {"name": "Moth", "path": "src/Moth.cs", "todos": ["1.1", "1.2"]},
              "2": {"name": "Lamp", "path": "src/Lamp.cs", "todos": ["2.1"]}}

    def test_a_change_of_a_part_that_is_handed_over_is_refused(self):
        bat = helpers.script(4, "Bat", ["4.1"], ["BatTests.Flies"])

        def add_bat(p, part):
            p["scripts"].append(bat)
            p["parts"][part]["scripts"].append(4)

        def drop_lamp(p):
            p["scripts"].pop(1)
            p["parts"][0]["scripts"].remove(2)

        cases = [(lambda p: add_bat(p, 0), texts.handed_added("Owner 4 Bat")),
                 (drop_lamp, texts.handed_removed("Owner 2 Lamp")),
                 (lambda p: p["scripts"][0]["todos"].append("1.3"), texts.handed_todo_added("Owner 1 Moth", "1.3")),
                 (lambda p: p["scripts"][0]["todos"].remove("1.1"), texts.handed_todo_removed("Owner 1 Moth", "1.1")),
                 (lambda p: p["scripts"][1].update(path="src/Light.cs"),
                  texts.handed_path("Owner 2 Lamp", "src/Lamp.cs", "src/Light.cs")),
                 (lambda p: p["parts"].reverse(), texts.handed_added("Owner 3 Keeper")),
                 (lambda p: p["parts"][0]["scripts"].append(p["parts"][1]["scripts"].pop()),
                  texts.handed_added("Owner 3 Keeper"))]
        for stored in ({"turn": "owner", "part": 0}, {"turn": "ai", "part": 1}):
            for change, item in cases:
                p = json.loads(json.dumps(full_plan(parts=TWO_PARTS)))
                change(p)
                self.planning(p, dict({"status": "build", "planHash": "0" * 64, "handed": self.HANDED}, **stored))
                text = self.refused("approve", "2 change: more")
                self.assertIn(texts.handed_changed(2), text)
                self.assertIn(texts.bullet(item), text.splitlines())
                self.assertTrue(text.endswith(texts.next_line("approve-phase", 2)))

    def test_other_changes_and_those_of_a_later_part_are_accepted(self):
        bat = helpers.script(4, "Bat", ["4.1"], ["BatTests.Flies"])
        for change in (lambda p: p["targets"][0].update(max=70),
                       lambda p: p["scripts"][0].update(name="Night moth", tests=["MothTests.Turns"]),
                       lambda p: p["scripts"][0]["todos"].reverse(),
                       lambda p: p["scripts"][2].update(path="src/Guard.cs", todos=["3.1", "3.2"]),
                       lambda p: (p["scripts"].append(bat),
                                  p["parts"].append({"name": "Bat", "tasks": ["Shell"], "scripts": [4]}))):
            p = json.loads(json.dumps(full_plan(parts=TWO_PARTS)))
            change(p)
            self.planning(p, {"status": "build", "planHash": "0" * 64, "handed": self.HANDED, "turn": "owner", "part": 0})
            self.accepted("approve", "2 change: more")
        self.planning(full_plan(parts=TWO_PARTS), {"status": "build", "planHash": "0" * 64, "turn": "ai", "part": 0})
        self.accepted("approve", "2 change: nothing is handed over yet")

    def tuned(self):
        """Approved, handed over, done and recorded, and then saved again: the results are old."""
        proj = self.planning()
        self.accepted("approve", "2")
        self.accepted("build", "2")
        proj.update_state(2, lambda d: d.update(turn="owner", handed={str(s["id"]): s for s in full_plan()["scripts"]}))
        helpers.make_project(self.tmp, files=FinishTests.CODE)
        path = self.tmp / "r.csv"
        path.write_text("".join("%s,pass\n" % t for t in FinishTests.PASSED))
        results.record(proj, 2, "Unit", path)
        self.assertEqual(self.data()["reached"], "tune")
        self.save_again()
        return proj

    def save_again(self):
        os.utime(str(self.tmp / "src" / "Moth.cs"), (helpers.FRESH - 1000,) * 2)

    def test_a_change_of_scripts_parts_or_tests_clears_reached(self):
        bat = helpers.script(4, "Bat", ["4.1"], ["BatTests.Flies"])
        for change in (lambda p: p["scripts"][0]["tests"].append("MothTests.Sleeps"),
                       lambda p: p["scripts"][0]["tests"].pop(),
                       lambda p: p["parts"].append({"name": "Rest", "tasks": ["Sound"], "scripts": []}),
                       lambda p: (p["scripts"].append(bat),
                                  p["parts"].append({"name": "Bat", "tasks": ["Shell"], "scripts": [4]}))):
            proj = self.tuned()
            p = json.loads(json.dumps(full_plan()))
            change(p)
            self.put_plan(p)
            self.accepted("approve", "2 change: more")
            self.assertNotIn("reached", self.data())
            self.assertEqual(state.compute(proj, 2).status, "build")
            shutil.rmtree(self.tmp / "Docs")

    def test_a_change_after_which_all_is_still_done_sets_reached_again(self):
        proj = self.tuned()
        os.utime(str(self.tmp / "src" / "Moth.cs"), (1000,) * 2)   # the results are fresh
        p = full_plan()
        p["scripts"][0].update(name="Night moth", tests=["MothTests.Turns"])
        self.put_plan(p)
        self.accepted("approve", "2 change: one test less")
        self.assertEqual(self.data()["reached"], "tune")
        self.save_again()
        self.assertEqual(state.compute(proj, 2).status, "tune")
        p["scripts"][0]["tests"].append("MothTests.Sleeps")
        self.put_plan(p)
        self.accepted("approve", "2 change: one more")
        self.assertNotIn("reached", self.data())

    def test_a_change_of_targets_or_questions_keeps_reached(self):
        proj = self.tuned()
        p = full_plan()
        p["targets"][0]["max"] = 70
        p["questions"][0]["text"] = "Which target?"
        self.put_plan(p)
        self.assertEqual(state.compute(proj, 2).status, "tune")
        self.accepted("approve", "2 change: wider")
        self.assertEqual((self.data()["reached"], state.compute(proj, 2).status), ("tune", "tune"))

    def recorded_with(self, plan_):
        """`reached` after a record that shows all done, while the plan is this one and not accepted."""
        proj = self.planning()
        self.accepted("approve", "2")
        proj.update_state(2, lambda d: d.update(turn="owner", part=0))
        helpers.make_project(self.tmp, files=FinishTests.CODE)
        path = self.tmp / "r.csv"
        path.write_text("".join("%s,pass\n" % t for t in FinishTests.PASSED))
        self.put_plan(plan_)
        results.record(proj, 2, "Unit", path)
        return self.data().get("reached")

    def test_scripts_that_are_not_accepted_yet_keep_reached_away(self):
        p = full_plan()
        p["scripts"][0]["tests"].pop()
        self.assertIsNone(self.recorded_with(p))

    def test_targets_and_questions_that_are_not_accepted_yet_do_not(self):
        self.assertEqual(self.recorded_with(dict(full_plan(), targets=[], questions=[])), "tune")

    def test_a_change_twice_compares_with_the_last_one(self):
        self.tuned()
        p = full_plan()
        p["scripts"][0]["tests"].append("MothTests.Sleeps")
        self.put_plan(p)
        self.accepted("approve", "2 change: one more test")
        self.project.update_state(2, lambda d: d.update(reached="tune"))
        p["targets"][0]["max"] = 70
        self.put_plan(p)
        self.accepted("approve", "2 change: wider")
        self.assertEqual(self.data()["reached"], "tune")

    def test_approved_already(self):
        self.planning()
        self.accepted("approve", "2")
        before = self.snapshot()
        self.accepted("approve", "2")
        self.assertEqual(self.snapshot(), before)
        self.refused("approve", "2 change: nothing")

    def test_done_skipped_and_not_started(self):
        for status in ("done", "skipped"):
            self.planning(stored={"status": status})
            self.refused("approve", "2")
        self.assertIn("/start-phase", self.refused("approve", "7"))
        self.refused("approve", "")
        self.refused("approve", "2 hello")

    def test_more_than_five_or_fewer_than_one_script_is_a_gap(self):
        def with_scripts(count):
            p = full_plan()
            p["scripts"] = [helpers.script(i, "S%d" % i, ["%d.1" % i], ["T.A%d" % i]) for i in range(1, count + 1)]
            p["parts"] = [{"name": "Part 1", "tasks": ["x"], "scripts": list(range(1, count + 1))}]
            return p

        for count in (0, 6):
            self.assertIn(texts.gap_script_count(count), self.gaps(with_scripts(count)))
        for count, note in ((1, True), (2, True), (3, False), (5, False)):
            self.planning(with_scripts(count))
            text = self.accepted("approve", "2")
            self.assertEqual(texts.few_scripts_note(count) in text, note, count)


class BuildTests(Base):
    def build(self, stored=None, plan_=None, files=None):
        st = {"status": "build", "branch": "stage-2"}
        st.update(stored or {})
        return self.make({2: {"state": st, "plan": plan_ or full_plan(parts=TWO_PARTS)}}, files=files)

    def test_blocked_before_approval(self):
        self.make({2: {"state": {"status": "planning"}, "plan": dict(full_plan(), targets=[])}})
        text = self.refused("build", "2")
        self.assertIn(texts.plan_not_approved(2), text)
        self.assertIn(texts.GAP_NO_TARGET, text)
        self.assertTrue(text.endswith(texts.next_line("start-phase", 2)))
        self.put_plan(full_plan())
        self.assertTrue(self.refused("build", "2").endswith(texts.next_line("approve-phase", 2)))

    def test_first_build_stores_the_turn_and_the_branch(self):
        self.build({"branch": "main"})
        self.accepted("build", "2")
        d = self.data()
        self.assertEqual((d["turn"], d["part"], d["branch"]), ("ai", 0, "stage-2"))

    def test_a_branch_made_after_the_approval_is_not_wrong(self):
        self.build({"branch": "main"})
        text = self.accepted("summarize", "2")
        self.assertNotIn("Wrong branch", text)
        self.assertTrue(text.endswith(texts.next_line("build-phase", 2)))

    def test_first_build_on_a_detached_head_stores_no_branch(self):
        self.branch = state.DETACHED
        self.build()
        self.accepted("build", "2")
        self.assertIsNone(self.data()["branch"])

    def test_wrong_branch_is_blocked_after_the_first_build(self):
        self.build({"turn": "ai", "part": 0})
        self.branch = "main"
        self.assertIn(texts.wrong_branch("stage-2", "main"), self.refused("build", "2"))

    def test_blocked_on_the_owners_turn(self):
        stored = {"turn": "owner", "part": 0,
                  "results": {"Unit": suite_result({"LampTests.Glows": "failed"})}}
        self.build(stored, files={"src/Moth.cs": shell(["1.2"]), "src/Lamp.cs": shell([])})
        text = self.refused("build")
        self.assertIn(texts.todos_left("Owner 1 Moth", 1), text)
        self.assertIn(texts.tests_failing("Owner 2 Lamp", ["LampTests.Glows"]), text)
        self.assertNotIn(texts.SURPRISED_MISSING, text)
        self.assertTrue(text.endswith(texts.next_line("summarize-phase", 2)))

    def test_names_the_part_and_open_tasks(self):
        self.build({"turn": "ai", "part": 0, "tasksDone": [{"part": 0, "index": 0}, {"part": 1, "index": 1}]})
        text = self.accepted("build", "2")
        self.assertIn("part 1 of 2", text)
        self.assertIn("Moths", text)
        self.assertIn(texts.task_line(0, "Shells", True), text)
        self.assertIn(texts.task_line(1, "Tests", False), text)
        for word in ("Owner 1 Moth", "Owner 2 Lamp", "src/Moth.cs", "1.1", "MothTests.Dies", "hand-over"):
            self.assertIn(word, text)
        self.assertNotIn("Keeper", text)

    def test_called_again_it_repeats(self):
        self.build()
        first = self.accepted("build", "2")
        before = self.snapshot()
        self.assertEqual(self.accepted("build", "2"), first)
        self.assertEqual(self.snapshot(), before)

    def test_next_part_when_the_owner_is_done(self):
        passed = {t: "passed" for t in ("MothTests.Turns", "MothTests.Dies", "LampTests.Glows")}
        self.build({"turn": "owner", "part": 0, "results": {"Unit": suite_result(passed)}},
                   files={"src/Moth.cs": shell([]), "src/Lamp.cs": shell([])})
        text = self.accepted("build", "2")
        self.assertEqual((self.data()["turn"], self.data()["part"]), ("ai", 1))
        self.assertIn("Owner 3 Keeper", text)

    def test_tune_and_wrap_up_name_summarize(self):
        passed = {t: "passed" for s in full_plan()["scripts"] for t in s["tests"]}
        self.build({"turn": "owner", "part": 0, "results": {"Unit": suite_result(passed)}}, full_plan(),
                   files={"src/%s.cs" % n: shell([]) for n in ("Moth", "Lamp", "Keeper")})
        text = self.refused("build", "2")
        self.assertIn("tune", text)
        self.assertTrue(text.endswith(texts.next_line("summarize-phase", 2)))

    def test_done_skipped_missing_and_garbage(self):
        for status in ("done", "skipped"):
            self.build({"status": status})
            self.refused("build", "2")
        self.assertIn("/start-phase", self.refused("build", "9"))
        self.refused("build", "abc")
        self.refused("build", "2 now")

    def test_empty_plan(self):
        self.build(plan_={"phase": 2})
        self.assertIn(texts.plan_missing("phase-2.plan.json"), self.refused("build", "2"))

    def test_no_number_is_the_latest_phase(self):
        self.build({"turn": "ai", "part": 0})
        self.accepted("build", "")
        self.make({3: {"state": {"status": "planning"}}})
        self.assertIn(texts.plan_not_approved(3), self.refused("build", "  "))


class HandOverTests(Base):
    SHELLS = {"src/Moth.cs": shell(["1.1", "1.2"]), "src/Lamp.cs": shell(["2.1"]), "src/Keeper.cs": shell(["3.1"])}
    OWNER = {t: "failed" for s in full_plan()["scripts"] for t in s["tests"]}

    def build(self, stored=None, plan_=None, files=None, tests=None, without=(), suites=("Unit",)):
        code = dict(self.SHELLS, **TEST_CODE)
        code.update(files or {})
        for path in without:
            code.pop(path)
        results = {"Unit": suite_result(dict(self.OWNER, **dict({"Other.Works": "passed"}, **(tests or {}))))}
        st = {"status": "build", "branch": "stage-2", "turn": "ai", "part": 0, "results": results}
        st.update(stored or {})
        return self.make({2: {"state": st, "plan": plan_ or full_plan()}}, code, {"suites": list(suites)})

    def blocked(self, n=2):
        before = self.snapshot()
        out = commands.hand_over(self.project, n)
        self.assertFalse(out.ok, out.text)
        self.assertEqual(self.snapshot(), before)
        self.assertTrue(out.text.splitlines()[-1].startswith("Next: "))
        return out.text

    def misses(self, *args, **kw):
        self.build(*args, **kw)
        return [x[4:] for x in self.blocked().splitlines() if x.startswith("  - ")]

    def without_test(self, name):
        return {k: v for k, v in self.OWNER.items() if k != name}

    def test_success_locks_and_passes_the_turn(self):
        self.build()
        out = commands.hand_over(self.project, None)
        self.assertEqual((out.ok, out.text), (True, "Phase 2, part 1 handed over. Your turn: 3 scripts, 4 TODOs.\n"
                                              "Next: open a new chat and type /summarize-phase 2"))
        d = self.data()
        self.assertEqual((d["turn"], d["part"]), ("owner", 0))
        self.assertEqual(d["locked"], ["src/Moth.cs", "src/Lamp.cs", "src/Keeper.cs"])
        self.assertEqual(d["handed"], {str(s["id"]): {k: s[k] for k in ("name", "path", "todos")}
                                       for s in full_plan()["scripts"]})

    def test_locks_are_a_union_and_singular_text(self):
        passed = {t: "passed" for t in ("MothTests.Turns", "MothTests.Dies", "LampTests.Glows")}
        self.build({"part": 1, "locked": ["src/Moth.cs", "src/Lamp.cs"], "handed": {"1": {}}}, full_plan(parts=TWO_PARTS), tests=passed,
                   files={"src/Moth.cs": shell([]), "src/Lamp.cs": shell([])})
        out = commands.hand_over(self.project, 2)
        self.assertIn("Phase 2, part 2 handed over. Your turn: 1 script, 1 TODO.", out.text)
        self.assertEqual(self.data()["locked"], ["src/Moth.cs", "src/Lamp.cs", "src/Keeper.cs"])
        self.assertEqual(self.data()["handed"], {"1": {}, "3": {"name": "Keeper", "path": "src/Keeper.cs", "todos": ["3.1"]}})

    def test_missing_todo(self):
        self.assertEqual(self.misses(files={"src/Moth.cs": shell(["1.1"])}),
                         [texts.todo_not_in_shell("Owner 1 Moth", "1.2", "src/Moth.cs")])
        self.assertEqual(self.misses(files={"src/Moth.cs": ""}),
                         [texts.todo_not_in_shell("Owner 1 Moth", t, "src/Moth.cs") for t in ("1.1", "1.2")])

    def test_missing_test(self):
        item = texts.test_not_in_code("Owner 1 Moth", "MothTests.Dies")
        self.assertEqual(self.misses(files={"src/MothTests.cs": "class MothTests { void Turns() {} void DiesNot() {} }"}),
                         [item])
        self.assertEqual(self.misses(files={"src/MothTests.cs": "class BigMothTests { void Turns() {} void Dies() {} }"}),
                         [texts.test_not_in_code("Owner 1 Moth", t) for t in ("MothTests.Turns", "MothTests.Dies")])

    def test_planned_names_with_namespace_and_cases_are_found(self):
        p = full_plan()
        p["scripts"][0]["tests"] = ["Game.MothTests.Turns", "MothTests.Dies(1)"]
        tests = {t: "failed" for script in p["scripts"] for t in script["tests"]}
        self.build({"results": {"Unit": suite_result(tests)}}, p)
        self.assertTrue(commands.hand_over(self.project, 2).ok)

    def test_project_suite_fails(self):
        self.assertEqual(self.misses(tests={"Other.Works": "failed"}), [texts.suite_failing("Unit", ["Other.Works"])])

    def test_suite_not_recorded_or_old(self):
        self.assertEqual(self.misses(suites=("Unit", "Play")), [texts.suite_not_recorded("Play")])
        old = {"results": {"Unit": suite_result(self.OWNER, OLD)}}
        items = self.misses(old)
        self.assertIn(texts.suite_old("Unit"), items)
        self.assertIn(texts.owner_test_not_run("Owner 2 Lamp", "LampTests.Glows"), items)

    def test_owner_tests_of_earlier_parts_must_pass(self):
        files = {"src/Moth.cs": shell([]), "src/Lamp.cs": shell([])}
        items = self.misses({"part": 1}, full_plan(parts=TWO_PARTS), files=files,
                            tests={"MothTests.Turns": "passed", "LampTests.Glows": "passed"})
        self.assertEqual(items, [texts.suite_failing("Unit", ["MothTests.Dies"])])

    def test_tests_that_were_not_run_again(self):
        known = ["Other.Works", "LaterTests.Runs"] + sorted(self.OWNER)
        passed = {"MothTests.Turns": "passed", "LampTests.Glows": "passed", "KeeperTests.Walks": "failed"}
        self.assertEqual(self.misses({"part": 1, "results": {"Unit": dict(suite_result(passed), known=known)}},
                                     full_plan(parts=TWO_PARTS),
                                     files={"src/Moth.cs": shell([]), "src/Lamp.cs": shell([]),
                                            "src/LaterTests.cs": "class LaterTests { void Runs() {} }"}),
                         [texts.suite_not_run("Unit", ["LaterTests.Runs", "MothTests.Dies"])])

    def test_a_renamed_test_that_is_called_does_not_block(self):
        self.build({"results": {"Unit": dict(suite_result(self.OWNER), known=sorted(self.OWNER) + ["GameTests.Move"])}},
                   files={"src/GameTests.cs": "class GameTests { void MovesLeft() { g.Move(); } }"})
        out = commands.hand_over(self.project, 2)
        self.assertTrue(out.ok, out.text)

    def test_an_owner_test_that_was_skipped_was_not_run(self):
        entry = dict(suite_result(self.without_test("LampTests.Glows")), skipped=["LampTests.Glows"])
        self.assertEqual(self.misses({"results": {"Unit": entry}}),
                         [texts.owner_test_not_run("Owner 2 Lamp", "LampTests.Glows")])

    def test_owner_tests_of_later_parts_need_not_be_run(self):
        tests = {k: v for k, v in self.OWNER.items() if not k.startswith("Keeper")}
        self.build({"results": {"Unit": dict(suite_result(tests), known=sorted(self.OWNER))}}, full_plan(parts=TWO_PARTS))
        self.assertTrue(commands.hand_over(self.project, 2).ok)

    def test_owner_tests_of_later_parts_may_fail_or_be_missing(self):
        self.build(plan_=full_plan(parts=TWO_PARTS), without=["src/Keeper.cs", "src/KeeperTests.cs"])
        self.assertTrue(commands.hand_over(self.project, 2).ok)

    def test_owner_test_already_passes(self):
        self.assertEqual(self.misses(tests={"LampTests.Glows": "passed"}),
                         [texts.owner_test_passes("Owner 2 Lamp", "LampTests.Glows")])

    def test_one_passing_case_counts_as_passing(self):
        self.assertEqual(self.misses(tests={"LampTests.Glows(1)": "passed"}),
                         [texts.owner_test_passes("Owner 2 Lamp", "LampTests.Glows")])

    def test_owner_test_not_run(self):
        results = {"Unit": suite_result(dict(self.without_test("LampTests.Glows"), **{"Other.Works": "passed"}))}
        self.assertEqual(self.misses({"results": results}), [texts.owner_test_not_run("Owner 2 Lamp", "LampTests.Glows")])

    def test_owner_tests_may_be_in_another_suite(self):
        results = {"Unit": suite_result({"Other.Works": "passed"}), "Owner": suite_result(self.OWNER)}
        self.build({"results": results}, suites=("Unit", "Owner"))
        self.assertTrue(commands.hand_over(self.project, 2).ok)

    def test_all_misses_are_listed_together(self):
        items = self.misses(files={"src/Moth.cs": shell(["1.1"]), "src/LampTests.cs": ""},
                            tests={"Other.Works": "failed", "KeeperTests.Walks": "passed"})
        self.assertEqual(items, [texts.todo_not_in_shell("Owner 1 Moth", "1.2", "src/Moth.cs"),
                                 texts.test_not_in_code("Owner 2 Lamp", "LampTests.Glows"),
                                 texts.owner_test_passes("Owner 3 Keeper", "KeeperTests.Walks"),
                                 texts.suite_failing("Unit", ["Other.Works"])])

    def test_only_on_the_ais_turn_of_a_build(self):
        for stored in ({"turn": "owner"}, {"turn": None}, {"status": "planning"}, {"status": "done"},
                       {"status": "skipped"}):
            self.build(stored)
            self.blocked()
        self.assertIn("/start-phase", self.blocked(9))

    def test_wrong_branch(self):
        self.build()
        self.branch = "main"
        self.assertIn(texts.wrong_branch("stage-2", "main"), self.blocked())

    def test_no_phase_at_all(self):
        self.make()
        self.assertIn("/start-phase 1", self.blocked(None))

    def test_part_without_scripts(self):
        rest = {"name": "Rest", "tasks": ["Sound"], "scripts": []}
        p = full_plan()
        p["parts"].append(rest)
        passed = {t: "passed" for t in self.OWNER}
        files = {f: shell([]) for f in self.SHELLS}
        self.build({"part": 1}, p, files, passed)
        out = commands.hand_over(self.project, 2)
        self.assertTrue(out.ok)
        self.assertEqual(out.text, "Phase 2, part 2 handed over.\n"
                                   "Next: open a new chat and type /summarize-phase 2")
        self.assertEqual(state.compute(self.project, 2).status, "tune")
        self.assertEqual(self.data()["reached"], "tune")
        os.utime(str(self.tmp / "src" / "Moth.cs"), (helpers.FRESH + 1000,) * 2)   # a tweak before the next record
        self.assertEqual(state.compute(self.project, 2).status, "tune")
        p["parts"].reverse()
        self.build({"part": 0}, p, files, {"Other.Works": "passed"})
        out = commands.hand_over(self.project, 2)
        self.assertTrue(out.text.endswith(texts.next_line("build-phase", 2)), out.text)

    def test_two_hand_overs_at_once_hand_over_once(self):
        self.build()
        outs = []
        threads = [threading.Thread(target=lambda: outs.append(commands.hand_over(self.project, 2))) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sorted(o.ok for o in outs), [False] * 4 + [True])


class FinishTests(Base):
    CODE = dict({"src/%s.cs" % n: shell([]) for n in ("Moth", "Lamp", "Keeper")}, **TEST_CODE)
    PASSED = {t: "passed" for s in full_plan()["scripts"] for t in s["tests"]}
    LOG = [{"kind": "measure", "target": "wins", "value": 50}, {"kind": "rating", "concept": "ai", "rating": "with help"}]

    def ready(self, stored=None, md=FULL_MD, files=None, plan_=None):
        st = {"status": "build", "branch": "stage-2", "turn": "owner", "part": 0, "log": self.LOG,
              "locked": ["src/Moth.cs"], "results": {"Unit": suite_result(self.PASSED)}}
        st.update(stored or {})
        plan_ = plan_ or full_plan()
        proj = self.make({2: {"state": st, "plan": plan_, "md": md}}, dict(self.CODE, **(files or {})))
        if "planHash" not in st:
            st["planHash"] = store.file_hash(proj.plan_path(2))
            helpers.write_json(proj.state_path(2), st)
        return proj

    def alone(self, item, *args, **kw):
        """The finish is refused with this one item, and nothing else."""
        self.ready(*args, **kw)
        text = self.refused("finish", "2")
        self.assertEqual([x[4:] for x in text.splitlines() if x.startswith("  - ")], [item])

    def md(self, old, new=""):
        self.assertIn(old, FULL_MD)
        return FULL_MD.replace(old, new)

    def test_all_good_writes_done_and_closing(self):
        self.merged = False
        self.ready()
        out = commands.run(self.project, "finish", "2")
        self.assertTrue(out.ok, out.text)
        closing = ("Phase 2 is done. Saved in Docs/learning/phase-2.md.\n"
                   "Branch stage-2: not merged.\n"
                   "Carried to phase 3: Enemy AI | start smaller\n"
                   "Next: commit, merge the branch, then open a new chat and type /start-phase 3")
        self.assertEqual(out.text, closing)   # nothing above it
        d = self.data()
        self.assertEqual((d["status"], d["locked"], d["closing"]), ("done", [], {"pending": True, "tries": 0}))
        self.assertEqual(commands.closing_text(self.project, 2), closing)

    def test_closing_text_of_a_merged_branch_and_no_weak_concept(self):
        log = self.LOG[:1] + [{"kind": "rating", "concept": "ai", "rating": "on my own"}]
        self.ready({"log": log})
        self.assertEqual(self.accepted("finish", "phase-2"),
                         "Phase 2 is done. Saved in Docs/learning/phase-2.md.\n"
                         "Branch stage-2: merged.\n"
                         "Carried to phase 3: no weak concept | start smaller\n"
                         "Next: commit, then open a new chat and type /start-phase 3")

    def test_closing_text_without_a_branch(self):
        self.branch = None
        self.ready({"branch": None})
        text = self.accepted("finish", "2")
        self.assertNotIn("Branch", text)
        self.assertEqual(text, commands.closing_text(self.project, 2))
        self.assertEqual(text.split("\n")[-1], "Next: open a new chat and type /start-phase 3")   # no git, no commit

    def test_closing_text_on_a_detached_head(self):
        self.branch = state.DETACHED
        self.ready({"branch": None})
        self.assertEqual(self.accepted("finish", "2").split("\n")[-1],
                         "Next: commit, then open a new chat and type /start-phase 3")

    def test_the_last_line_is_the_one_of_the_design(self):
        design = (version.ROOT / "docs" / "design.md").read_text(encoding="utf-8")
        self.merged = False
        self.ready()
        self.assertIn("\n%s\n```" % self.accepted("finish", "2").split("\n")[-1], design)

    def test_second_time_changes_nothing(self):
        self.ready()
        self.accepted("finish", "2")
        before = self.snapshot()
        self.branch = "main"
        self.assertIn(texts.done_text(2), self.accepted("finish", "2"))
        self.assertEqual(self.snapshot(), before)

    def test_todo_left_in_an_owner_script(self):
        self.alone(texts.todos_left("Owner 1 Moth", 1), files={"src/Moth.cs": shell(["1.2"])})

    def test_todo_left_in_another_file(self):
        self.alone(texts.todo_elsewhere("2.1", "src/Extra.cs"), files={"src/Extra.cs": shell(["2.1", "9.1"])})

    def test_leftovers_of_a_skipped_phase_do_not_count(self):
        other = full_plan(1)
        for sc, name in zip(other["scripts"], ("Bat", "Wolf", "Door")):
            sc.update(name=name, path="src/%s.cs" % name, tests=["%sTests.Moves" % name])
        self.ready(files={"src/Bat.cs": shell(["1.2"]),
                          "src/BatTests.cs": 'class BatTests {\n[Explicit("Owner")] void Moves() {} }\n'})
        helpers.make_project(self.tmp, phases={1: {"state": {"status": "skipped", "skip": "x"}, "plan": other}})
        self.accepted("finish", "2")

    def test_owner_mark_left(self):
        self.alone(texts.owner_mark_left("src/LampTests.cs:1"),
                   files={"src/LampTests.cs": '[Explicit("Owner")] class LampTests { void Glows() {} }'})

    def test_suite_not_recorded(self):
        p = full_plan()
        for s in p["scripts"]:
            s["tests"] = []   # so that only the suite itself is missing
        self.alone(texts.suite_not_recorded("Unit"), {"results": {}}, plan_=p)

    def test_suite_older_than_the_code(self):
        p = full_plan()
        for s in p["scripts"]:
            s["tests"] = []
        self.alone(texts.suite_old("Unit"), {"results": {"Unit": suite_result(self.PASSED, OLD)}}, plan_=p)

    def test_suite_failing(self):
        self.alone(texts.suite_failing("Unit", ["Other.Works"]),
                   {"results": {"Unit": suite_result(dict(self.PASSED, **{"Other.Works": "failed"}))}})

    def test_tests_that_were_not_run_again(self):
        entry = dict(suite_result(self.PASSED), known=["GameTests.Starts"] + sorted(self.PASSED))
        self.alone(texts.suite_not_run("Unit", ["GameTests.Starts"]), {"results": {"Unit": entry}},
                   files={"src/GameTests.cs": "class GameTests { void Starts() {} }"})
        self.assertIn(texts.suite_not_run("Unit", ["GameTests.Starts"]), self.accepted("summarize", "2"))

    def test_a_renamed_test_that_is_called_does_not_block(self):
        self.ready({"results": {"Unit": dict(suite_result(self.PASSED), known=["GameTests.Move"])}},
                   files={"src/GameTests.cs": "class GameTests { void MovesLeft() { g.Move(); } }"})
        self.accepted("finish", "2")

    def test_an_ignored_test_that_was_reported_does_not_block(self):
        entry = dict(suite_result(self.PASSED), known=["GameTests.Move"], skipped=["Game.GameTests.Move"])
        self.ready({"results": {"Unit": entry}},
                   files={"src/GameTests.cs": 'class GameTests { [Ignore("x")] void Move() {} }'})
        self.accepted("finish", "2")

    def test_a_skipped_owner_test_is_not_done(self):
        passed = {k: v for k, v in self.PASSED.items() if k != "LampTests.Glows"}
        entry = dict(suite_result(passed), known=sorted(self.PASSED), skipped=["LampTests.Glows"])
        self.alone(texts.tests_not_run("Owner 2 Lamp", ["LampTests.Glows"]), {"results": {"Unit": entry}})

    def test_an_owner_test_that_was_not_run_again_is_named_once(self):
        passed = {k: v for k, v in self.PASSED.items() if k != "LampTests.Glows"}
        entry = dict(suite_result(passed), known=sorted(self.PASSED))
        self.alone(texts.tests_not_run("Owner 2 Lamp", ["LampTests.Glows"]), {"results": {"Unit": entry}})

    def test_old_results_in_the_wrap_up_keep_it_open(self):
        old = {"reached": "tune", "results": {"Unit": suite_result(self.PASSED, OLD)}}
        proj = self.ready(old)
        self.assertEqual(state.compute(proj, 2).status, "wrap-up")
        text = self.refused("finish", "2")
        for label in ("Owner 1 Moth", "Owner 2 Lamp", "Owner 3 Keeper"):
            self.assertIn(texts.tests_old(label), text)
        self.assertIn(texts.suite_old("Unit"), text)
        self.assertTrue(text.endswith(texts.next_line("summarize-phase", 2)))
        self.assertIn(texts.build_is_over(2, "wrap-up"), self.refused("build", "2"))
        self.ready(dict(old, results={"Unit": suite_result(self.PASSED)}))
        self.accepted("finish", "2")

    def test_a_run_of_one_script_in_the_wrap_up_keeps_it_open(self):
        for tests in ({"MothTests.Turns": "passed", "MothTests.Dies": "passed"}, {"GameTests.Starts": "passed"}):
            proj = self.ready({"reached": "tune", "results": {"Unit": suite_result(tests)}})
            self.assertEqual(state.compute(proj, 2).status, "wrap-up")
            self.assertIn(texts.tests_not_run("Owner 2 Lamp", ["LampTests.Glows"]), self.refused("finish", "2"))

    def test_target_without_value_or_reason(self):
        self.alone(texts.target_open("wins"), {"log": self.LOG[1:]})

    def test_target_missed_without_reason(self):
        self.alone(texts.target_open("wins"),
                   {"log": self.LOG + [{"kind": "measure", "target": "wins", "value": 61}]})

    def test_target_missed_with_a_reason_is_fine(self):
        self.ready({"log": self.LOG[1:] + [{"kind": "measure", "target": "wins", "value": 61},
                                           {"kind": "reason", "target": "wins", "text": "more fun"}]})
        self.accepted("finish", "2")

    def test_concept_without_an_answer(self):
        self.alone(texts.answer_missing("Enemy AI"), md=self.md("It takes the nearest lamp in range."))

    def test_concept_without_a_rating(self):
        self.alone(texts.rating_missing("Enemy AI"), {"log": self.LOG[:1]})

    def test_last_rating_is_cant_yet(self):
        self.alone(texts.rating_missing("Enemy AI"),
                   {"log": self.LOG + [{"kind": "rating", "concept": "ai", "rating": "can't yet"}]})

    def test_concept_without_a_summary(self):
        self.alone(texts.summary_missing("Enemy AI"), md=self.md("A state machine with two states."))

    def test_too_few_and_too_many_lessons(self):
        self.alone(texts.lessons_count(2), md=self.md("- three\n"))
        self.alone(texts.lessons_count(6), md=self.md("- three\n", "- three\n- 4\n- 5\n- 6\n"))

    def test_process_surprised_missing(self):
        self.alone(texts.SURPRISED_MISSING, md=self.md(" the tests came first"))

    def test_process_differently_missing(self):
        self.alone(texts.DIFFERENTLY_MISSING, md=self.md(" start smaller"))

    def test_changed_plan(self):
        self.alone(texts.plan_changed(2, "phase-2.plan.json"), {"planHash": "0" * 64})

    def test_part_not_handed_over(self):
        self.alone(texts.part_not_handed(1, "Rest"),
                   plan_=full_plan(parts=full_plan()["parts"] + [{"name": "Rest", "tasks": ["x"], "scripts": []}]))

    def test_wrong_branch(self):
        self.ready()
        self.branch = "main"
        self.assertIn(texts.wrong_branch("stage-2", "main"), self.refused("finish", "2"))

    def test_all_misses_are_listed_together(self):
        self.ready({"log": []}, md="", files={"src/Moth.cs": shell(["1.2"])})
        text = self.refused("finish", "2")
        for item in (texts.todos_left("Owner 1 Moth", 1), texts.target_open("wins"), texts.answer_missing("Enemy AI"),
                     texts.rating_missing("Enemy AI"), texts.summary_missing("Enemy AI"), texts.lessons_count(0),
                     texts.SURPRISED_MISSING, texts.DIFFERENTLY_MISSING):
            self.assertIn(item, text)

    def test_planning_skipped_missing_and_garbage(self):
        self.ready({"status": "planning"})
        self.assertIn(texts.plan_not_approved(2), self.refused("finish", "2"))
        self.ready({"status": "skipped"})
        self.refused("finish", "2")
        self.assertIn("/start-phase", self.refused("finish", "9"))
        for argument in ("", "abc", "2 now"):
            self.refused("finish", argument)

    def test_status_and_finish_agree(self):
        self.ready()
        self.assertTrue(self.accepted("summarize", "2").endswith(texts.next_line("finish-phase", 2)))
        self.accepted("finish", "2")


class SummarizeTests(Base):
    def test_shows_the_status(self):
        proj = self.make({2: {"state": {"status": "build", "branch": "stage-2", "turn": "ai"}, "plan": full_plan()}})
        self.assertEqual(self.accepted("summarize", "2"), render.status(state.compute(proj, 2)).rstrip("\n"))

    def test_wrong_branch_is_ok_and_says_so(self):
        self.make({2: {"state": {"status": "build", "branch": "stage-2", "turn": "ai"}, "plan": full_plan()}})
        self.branch = "main"
        self.assertIn(texts.wrong_branch("stage-2", "main"), self.accepted("summarize", "2"))

    def test_no_phase_at_all(self):
        self.make()
        for argument in ("", "2"):
            self.assertIn("/start-phase", self.refused("summarize", argument))


class ParseTests(Base):
    """Review Focus 5."""

    def typed(self, prompt):
        name, argument = commands.parse(prompt)
        self.assertEqual(name, "summarize-phase")
        return commands.run(self.project, name, argument)

    def setUp(self):
        super().setUp()
        self.make({2: {"state": {"status": "planning"}}})

    def test_plugin_name_in_front(self):
        self.assertTrue(self.typed("/guided-learning:summarize-phase 2").text.startswith("Phase 2 - planning"))

    def test_extra_spaces(self):
        self.assertTrue(self.typed("  /summarize-phase    2   \n").text.startswith("Phase 2 - planning"))

    def test_phase_2(self):
        self.assertTrue(self.typed("/summarize-phase phase-2").text.startswith("Phase 2 - planning"))

    def test_abc_is_a_clear_message(self):
        out = self.typed("/summarize-phase abc")
        self.assertFalse(out.ok)
        self.assertIn('"abc" is not a phase number', out.text)

    def test_missing_phase_is_a_clear_message(self):
        out = self.typed("/summarize-phase 7")
        self.assertFalse(out.ok)
        self.assertIn("Phase 7 does not exist. Phases: 2.", out.text)
        self.assertTrue(out.text.endswith(texts.next_line("start-phase", 3)))

    def test_all_six_commands_and_nothing_else(self):
        for name in texts.COMMANDS:
            self.assertEqual(commands.parse("/%s" % name), (name, ""))
        self.assertEqual(commands.parse("/start-phase 2 skip: too\nlong"), ("start-phase", "2 skip: too\nlong"))
        for prompt in ("", "hello", "/help", "type /start-phase 2", "/start-phases 2", "/start", "/other:start-phase 2",
                       "start-phase 2", "/ start-phase", None):
            self.assertIsNone(commands.parse(prompt))


class DoneElsewhereTests(GitBase):
    """A phase that is done and committed on its branch, and not merged into the one that is checked out."""

    RECORD = {"branch": "stage-1", "done": True, "locked": []}

    @property
    def local(self):
        return self.project.root / ".claude" / "learning" / "local" / "open.json"

    def finish(self, n=1, back="main", **more):
        """Close phase n on the branch stage-n, made from here, and check out another branch."""
        if n == 1:
            self.make()
        branch = "stage-%d" % n
        self.git("switch", "-q", "-c", branch)
        st = dict({"status": "build", "branch": branch, "turn": "owner", "part": 0, "log": FinishTests.LOG,
                   "results": {"Unit": suite_result(FinishTests.PASSED)}}, **more)
        helpers.make_project(self.project.root, {n: {"state": st, "plan": full_plan(n), "md": FULL_MD}}, files=FinishTests.CODE)
        self.accepted("finish", str(n))
        self.commit()
        if back:
            self.git("switch", "-q", back)

    def files(self):
        return {str(f): f.read_bytes() for f in self.project.root.rglob("*") if f.is_file() and ".git" not in f.parts}

    def merge_line(self, n=1):
        return "Next: merge the branch, then open a new chat and type /start-phase %d" % (n + 1)

    def assertNotMerged(self, text, n=1):
        self.assertIn(texts.done_not_merged(n, "stage-%d" % n), text)
        self.assertTrue(text.endswith(self.merge_line(n)), text)

    COMMANDS = [("start", "1"), ("start", "2"), ("start", "3"), ("start", "1 skip: x"), ("start", "2 skip: x"),
                ("start", "3 skip: x"), ("approve", "1"), ("approve", "1 change: x"), ("build", "1"), ("build", ""),
                ("finish", "1")]

    def test_the_text_names_the_branch_and_the_way_on(self):
        text = texts.done_not_merged(1, "stage-1")
        self.assertIn("Phase 1 is done on branch stage-1, not merged", text)
        self.assertIn("/start-phase 2", text)
        self.assertIn("without merging: git switch stage-1, and there type %s" % texts.skip_command(2), text)
        self.assertIn(texts.skip_command(4), texts.done_not_merged(1, "stage-1", 4))
        self.assertNotRegex(text, "delete|branch -")

    def follow_the_skip(self, n, branch, following):
        """Do what the refusal says for going on without merging."""
        text = self.refused("start", str(following))
        self.assertIn("git switch %s, and there type %s" % (branch, texts.skip_command(following)), text)
        self.git("switch", "-q", branch)
        refused = self.refused("start", str(following))
        self.assertIn(texts.previous_not_merged(following, branch) if following == n + 1
                      else texts.previous_missing(following), refused)   # only the skip leaves the merge out
        before = self.project.state_path(n).read_bytes()
        shown = self.accepted("start", "%d skip: merged later" % following)
        self.assertIn(texts.carried_concept("Enemy AI") if following == n + 1 else "was skipped", shown)
        self.assertEqual(self.project.state_path(n).read_bytes(), before)
        self.assertEqual(store.read(self.project.state_path(following))["status"], "planning")

    def test_going_on_without_merging_works_as_the_text_says(self):
        self.finish()
        self.follow_the_skip(1, "stage-1", 2)
        helpers.write_json(self.project.plan_path(2), full_plan(2))
        self.accepted("approve", "2")
        self.accepted("build", "2")
        self.assertEqual(store.read(self.project.state_path(1))["status"], "done")
        self.assertNotIn("skip", store.read(self.project.state_path(1)))
        self.assertEqual(store.read(self.project.state_path(2))["branch"], "stage-1")

    def test_going_on_without_merging_after_a_phase_that_is_skipped_here(self):
        self.finish()
        helpers.make_project(self.project.root, {2: {"state": {"status": "skipped", "skip": "x"}}})
        self.commit()
        self.follow_the_skip(1, "stage-1", 3)
        self.assertEqual(store.read(self.project.state_path(2))["status"], "skipped")

    def assertLater(self, text, n, branch, later, on):
        """Phase n is done on a branch, and a later phase was started: no advice to start one."""
        self.assertIn("Phase %d is done on branch %s, not merged" % (n, branch), text)
        self.assertIn("Phase %d was started after it, on branch %s. To go on: git switch %s" % (later, on, on), text)
        self.assertNotIn("/start-phase", text)
        self.assertTrue(text.endswith(texts.next_line("summarize-phase", later)), text)

    def test_a_later_phase_that_is_open_is_named(self):
        self.finish()
        self.follow_the_skip(1, "stage-1", 2)
        helpers.write_json(self.project.plan_path(2), full_plan(2))
        self.accepted("approve", "2")
        self.accepted("build", "2")
        self.commit()
        self.git("switch", "-q", "main")
        self.assertLater(self.accepted("summarize", "1"), 1, "stage-1", 2, "stage-1")

    def test_a_later_phase_that_is_done_here_is_not_meant(self):
        self.finish()
        helpers.make_project(self.project.root, {2: {"state": {"status": "done", "branch": "stage-2"}}})
        helpers.write_json(self.local, {"1": self.RECORD, "2": {"branch": "stage-2", "done": True, "locked": []}})
        self.assertIn(texts.done_not_merged(1, "stage-1", 3), self.accepted("summarize", "1"))

    def test_an_open_phase_is_still_checked_without_the_skip(self):
        self.finish()
        self.git("switch", "-q", "stage-1")
        self.accepted("start", "2 skip: merged later")
        self.assertIn(texts.previous_open(3), self.refused("start", "3"))

    def test_every_command_names_the_branch_and_the_merge(self):
        self.finish()
        self.assertFalse(self.project.state_path(1).exists())
        before = self.files()
        for argument in ("", "1"):
            text = self.accepted("summarize", argument)
            self.assertTrue(text.startswith("Phase 1 - done"), text)
            self.assertNotMerged(text)
        for name, argument in self.COMMANDS:
            self.assertNotMerged(self.refused(name, argument))
        out = commands.hand_over(self.project, None)
        self.assertFalse(out.ok)
        self.assertNotMerged(out.text)
        self.assertEqual(commands.suggestion(self.project), self.merge_line())
        self.assertEqual(self.files(), before)
        self.assertEqual(self.git("status", "--porcelain"), "")

    def test_on_a_detached_head(self):
        self.finish()
        self.git("switch", "-q", "--detach", "main")
        self.assertNotMerged(self.accepted("summarize"))
        self.git("switch", "-q", "--detach", "stage-1")   # here the files are
        self.assertIn(texts.done_text(1), self.accepted("summarize"))

    def test_a_phase_that_does_not_exist_names_the_merge(self):
        self.finish()
        for name in ("summarize", "approve", "build", "finish"):
            text = self.refused(name, "2")
            self.assertIn(texts.no_phase(2, []), text)
            self.assertTrue(text.endswith(self.merge_line()), text)

    def test_an_older_phase_file_counts_as_missing(self):
        self.finish()
        for old in ({"status": "planning"}, {"status": "build", "branch": "stage-1"},
                    {"status": "build", "branch": "stage-1", "turn": "owner", "part": 0}):
            helpers.make_project(self.project.root, {1: {"state": old, "plan": full_plan(1)}})
            self.assertNotMerged(self.accepted("summarize"))
            for name, argument in self.COMMANDS:
                self.assertNotMerged(self.refused(name, argument))
            self.assertEqual(store.read(self.project.state_path(1)), old)

    def test_a_phase_that_is_done_or_skipped_here_is_as_before(self):
        self.finish()
        for status in ("done", "skipped"):
            helpers.make_project(self.project.root, {1: {"state": {"status": status}, "plan": full_plan(1)}})
            text = self.accepted("summarize")
            self.assertTrue(text.startswith("Phase 1 - %s" % status), text)
            self.assertNotIn("not merged", text)

    def test_on_the_branch_itself_everything_is_as_before(self):
        self.finish(back=None)
        self.assertIn("Scorecard of phase 1", self.accepted("summarize"))
        self.assertIn(texts.previous_not_merged(2, "stage-1"), self.refused("start", "2"))
        self.assertIn(texts.already_started(1, "done"), self.refused("start", "1"))
        self.assertIn(texts.done_text(1), self.accepted("finish", "1"))
        self.accepted("start", "2 skip: merged later")
        self.assertEqual(store.read(self.local), {"1": self.RECORD})

    def test_on_a_branch_made_from_it_everything_is_as_before(self):
        self.finish()
        self.git("switch", "-q", "-c", "stage-2", "stage-1")
        self.assertIn("Scorecard of phase 1", self.accepted("summarize"))
        self.accepted("start", "2")

    def test_after_the_merge(self):
        self.finish()
        self.git("merge", "-q", "--no-ff", "-m", "x", "stage-1")
        self.assertIn("Scorecard of phase 1", self.accepted("summarize"))
        self.accepted("start", "2")
        self.assertEqual(store.read(self.project.state_path(2))["status"], "planning")

    def test_after_the_merge_and_without_the_branch(self):
        self.finish()
        self.git("merge", "-q", "--ff-only", "stage-1")
        self.git("branch", "-q", "-D", "stage-1")
        self.accepted("start", "2")

    def test_after_a_squash_merge(self):
        self.finish()
        self.git("merge", "-q", "--squash", "stage-1")
        self.git("commit", "-q", "-m", "squashed")
        self.assertIn("Scorecard of phase 1", self.accepted("summarize"))
        self.assertIn(texts.previous_not_merged(2, "stage-1"), self.refused("start", "2"))   # as before
        self.git("branch", "-q", "-D", "stage-1")
        self.accepted("start", "2")

    def test_a_branch_that_is_gone_has_no_effect(self):
        self.finish()
        self.git("branch", "-q", "-m", "stage-1", "renamed")
        self.assertIn(texts.NO_PHASE_YET, self.refused("summarize"))
        self.assertIn(texts.previous_missing(2), self.refused("start", "2"))
        self.accepted("start", "1")
        self.assertEqual(store.read(self.local), {})

    def test_a_merge_without_the_phase_files_has_no_effect(self):
        self.finish()
        self.git("merge", "-q", "--ff-only", "stage-1")
        self.git("rm", "-q", "-r", "Docs")
        self.assertIn(texts.NO_PHASE_YET, self.refused("summarize"))

    def test_without_git_everything_is_as_before(self):
        self.finish()
        with mock.patch.object(state, "_git", return_value=None):
            self.assertIn(texts.NO_PHASE_YET, self.refused("summarize"))
            self.assertIn(texts.previous_missing(2), self.refused("start", "2"))

    def test_without_git_there_is_no_record(self):
        root = helpers.make_project(self.tmp / "game", {1: {"state": {
            "status": "build", "turn": "owner", "part": 0, "log": FinishTests.LOG,
            "results": {"Unit": suite_result(FinishTests.PASSED)}}, "plan": full_plan(1), "md": FULL_MD}}, files=FinishTests.CODE)
        self.project = project.find(root)
        self.accepted("finish", "1")
        self.assertFalse(self.local.exists())
        self.accepted("start", "2")

    def test_if_git_cannot_tell_it_is_as_before(self):
        self.finish()
        with mock.patch.object(state, "_ref_exists", side_effect=state._GitError()):
            self.assertIn(texts.NO_PHASE_YET, self.refused("summarize"))

    def test_several_phases(self):
        self.finish(1)
        self.git("merge", "-q", "--ff-only", "stage-1")
        self.finish(2)
        self.assertNotMerged(self.accepted("summarize"), 2)
        self.assertIn("Scorecard of phase 1", self.accepted("summarize", "1"))
        self.assertIn(texts.done_text(1), self.accepted("finish", "1"))
        for argument in ("2", "3", "4", "3 skip: x"):
            self.assertNotMerged(self.refused("start", argument), 2)
        self.assertIn(texts.already_started(1, "done"), self.refused("start", "1"))

    def test_two_phases_that_are_not_merged(self):
        self.finish(1)
        self.git("switch", "-q", "stage-1")
        self.finish(2)
        self.assertNotMerged(self.accepted("summarize"), 2)
        self.assertLater(self.accepted("summarize", "1"), 1, "stage-1", 2, "stage-2")
        self.assertLater(self.refused("start", "1"), 1, "stage-1", 2, "stage-2")
        for argument in ("2", "3", "4"):   # of the two, the later one
            self.assertNotMerged(self.refused("start", argument), 2)
        self.git("merge", "-q", "--ff-only", "stage-2")   # brings both
        self.accepted("start", "3")

    def test_the_text_names_the_first_phase_that_is_not_done_here(self):
        self.finish()
        for here, following in (("done", 3), ("skipped", 3), ("planning", 2), ("build", 2)):
            helpers.make_project(self.project.root, {2: {"state": {"status": here}, "plan": full_plan(2)}})
            for out in (commands.run(self.project, "start", "3"), commands.run(self.project, "summarize", "1")):
                self.assertIn("/start-phase %d. " % following, out.text.splitlines()[-2], here)
                self.assertEqual(out.text.splitlines()[-1], self.merge_line(following - 1), here)
        helpers.make_project(self.project.root, {2: {"state": {"status": "done"}}, 3: {"state": {"status": "done"}}})
        self.assertIn("/start-phase 4. ", self.refused("start", "4"))

    def test_a_skip_drops_an_open_record_that_was_left(self):
        for status in ("done", "skipped"):
            self.make({1: {"state": {"status": status, "branch": "stage-1"}, "plan": full_plan(1)}})
            left = {"branch": "stage-1", "locked": ["src/Moth.cs"], "built": True}
            helpers.write_json(self.local, {"1": left, "7": left})
            self.accepted("start", "2 skip: x")
            self.assertEqual(store.read(self.local), {"7": left}, status)
            shutil.rmtree(self.project.root / "Docs")

    def test_the_next_phase_is_open_on_its_branch(self):
        self.finish(back=None)
        self.git("switch", "-q", "-c", "stage-2")
        self.accepted("start", "2")
        helpers.write_json(self.project.plan_path(2), full_plan(2))
        self.accepted("approve", "2")
        self.accepted("build", "2")
        self.commit()
        self.git("switch", "-q", "main")
        wrong = texts.wrong_branch("stage-2", "main")
        self.assertIn(wrong, self.accepted("summarize"))
        self.assertIn(wrong, self.refused("start", "2"))
        self.assertIn(wrong, self.refused("start", "3"))
        self.assertLater(self.accepted("summarize", "1"), 1, "stage-1", 2, "stage-2")
        self.assertLater(self.refused("start", "1"), 1, "stage-1", 2, "stage-2")

    def test_the_record_of_a_skipped_phase_is_removed(self):
        self.finish()
        self.git("merge", "-q", "--squash", "stage-1")
        self.git("commit", "-q", "-m", "squashed")
        self.project.update_state(1, lambda d: d.update(status="skipped"))
        self.accepted("start", "2 skip: x")
        self.assertEqual(store.read(self.local), {})

    def test_a_done_phase_gets_no_record_from_a_skip(self):
        self.make({1: {"state": {"status": "done", "branch": "stage-1"}, "plan": full_plan(1)}})
        self.accepted("start", "2 skip: x")
        self.assertFalse(self.local.exists())

    def test_damaged_records_have_no_effect(self):
        self.finish()
        for odd in ({"done": True, "locked": []}, {"branch": 5, "done": True, "locked": []}, {"branch": "stage-1"}, 5):
            helpers.write_json(self.local, {"1": odd})
            self.assertIn(texts.NO_PHASE_YET, self.refused("summarize"), odd)
        helpers.write_json(self.local, {"1": self.RECORD, "x": self.RECORD})
        self.assertNotMerged(self.accepted("summarize"))

    def test_nothing_changes_in_a_rehearsal(self):
        self.finish()
        fake = project.Project(self.project.root / ".claude" / "learning" / "rehearsal", self.project.settings)
        helpers.write_json(fake.root / ".claude" / "learning" / "local" / "open.json", {"1": self.RECORD})
        self.assertEqual(fake.done_phases(), {})
        fake.note_open(2, {"status": "done", "branch": "stage-2"})
        self.assertEqual(store.read(fake.root / ".claude" / "learning" / "local" / "open.json"), {"1": self.RECORD})


if __name__ == "__main__":
    unittest.main()
