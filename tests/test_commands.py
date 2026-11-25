import shutil
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import helpers
from helpers import FULL_MD, OLD, TEST_CODE, TWO_PARTS, full_plan, shell, suite_result
from gl import commands, project, render, state, store, texts


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
        self.assertTrue(text.endswith(texts.next_line("approve-phase", 1)))

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
        self.accepted("start", "2 skip: merge comes later")
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
        self.assertIn("phase-1.plan.json", self.accepted("start", "1"))
        self.assertEqual(self.snapshot(), before)
        self.make({1: {"state": {"status": "build", "turn": "ai"}, "plan": full_plan(1)}})
        self.assertTrue(self.refused("start", "1").endswith(texts.next_line("build-phase", 1)))
        self.make({1: {"state": {"status": "done"}}})
        self.assertTrue(self.refused("start", "1").endswith(texts.next_line("start-phase", 2)))

    def test_a_skipped_phase_can_be_planned_again(self):
        self.make({1: {"state": {"status": "skipped", "skip": "x", "turn": "owner", "part": 1, "planHash": "h",
                                 "locked": ["src/Moth.cs"], "branch": "b", "carried": ["old"],
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
        self.assertTrue(text.endswith(texts.next_line("approve-phase", 2)))
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
        ]
        for fn, item in cases:
            self.assertIn(item, change(fn))

    def test_one_sided_target_and_empty_part_are_fine(self):
        p = full_plan(parts=TWO_PARTS + [{"name": "Rest", "tasks": ["Sound"], "scripts": []}])
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
        self.assertIn(texts.GAP_NO_TARGET, self.refused("approve", "2 change: none"))

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
        self.assertTrue(text.endswith(texts.next_line("approve-phase", 2)))

    def test_first_build_stores_the_turn_and_the_branch(self):
        self.build({"branch": "main"})
        self.accepted("build", "2")
        d = self.data()
        self.assertEqual((d["turn"], d["part"], d["branch"]), ("ai", 0, "stage-2"))

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

    def test_locks_are_a_union_and_singular_text(self):
        passed = {t: "passed" for t in ("MothTests.Turns", "MothTests.Dies", "LampTests.Glows")}
        self.build({"part": 1, "locked": ["src/Moth.cs", "src/Lamp.cs"]}, full_plan(parts=TWO_PARTS), tests=passed,
                   files={"src/Moth.cs": shell([]), "src/Lamp.cs": shell([])})
        out = commands.hand_over(self.project, 2)
        self.assertIn("Phase 2, part 2 handed over. Your turn: 1 script, 1 TODO.", out.text)
        self.assertEqual(self.data()["locked"], ["src/Moth.cs", "src/Lamp.cs", "src/Keeper.cs"])

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
        self.assertEqual(out.text, "Phase 2 is done. Saved in Docs/learning/phase-2.md.\n"
                                   "Branch stage-2: not merged.\n"
                                   "Carried to phase 3: Enemy AI | start smaller\n"
                                   "Next: merge the branch, then open a new chat and type /start-phase 3")
        d = self.data()
        self.assertEqual((d["status"], d["locked"], d["closing"]), ("done", [], {"pending": True, "tries": 0}))
        self.assertEqual(commands.closing_text(self.project, 2), out.text)

    def test_closing_text_of_a_merged_branch_and_no_weak_concept(self):
        log = self.LOG[:1] + [{"kind": "rating", "concept": "ai", "rating": "on my own"}]
        self.ready({"log": log})
        self.assertEqual(self.accepted("finish", "phase-2"),
                         "Phase 2 is done. Saved in Docs/learning/phase-2.md.\n"
                         "Branch stage-2: merged.\n"
                         "Carried to phase 3: no weak concept | start smaller\n"
                         "Next: open a new chat and type /start-phase 3")

    def test_closing_text_without_a_branch(self):
        self.branch = None
        self.ready({"branch": None})
        self.assertNotIn("Branch", self.accepted("finish", "2"))

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


if __name__ == "__main__":
    unittest.main()
