import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

import helpers
from helpers import FULL_MD, TEST_CODE, TWO_PARTS, full_plan, shell
from gl import log, project, results, state, store, texts

LEARNING = Path(__file__).resolve().parent.parent / "scripts" / "learning.py"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def make(self, stored=None, phases=None, files=None):
        st = {"status": "build", "turn": "owner", "part": 0}
        st.update(stored or {})
        root = helpers.make_project(self.tmp, phases=phases or {2: {"state": st, "plan": full_plan(parts=TWO_PARTS),
                                                                    "md": FULL_MD}}, files=files)
        self.project = project.find(root)
        return self.project

    def data(self, n=2):
        return store.read(self.project.state_path(n))


class LogTests(Base):
    def setUp(self):
        super().setUp()
        self.make()

    def add(self, kind, **fields):
        return log.add(self.project, 2, kind, **fields)

    def rejects(self, kind, **fields):
        before = self.project.state_path(2).read_bytes()
        with self.assertRaises(log.LogError) as e:
            self.add(kind, **fields)
        self.assertEqual(self.project.state_path(2).read_bytes(), before)
        return str(e.exception)

    def last(self):
        entry = dict(self.data()["log"][-1])
        self.assertTrue(entry.pop("time"))
        return entry

    def test_every_kind_is_stored(self):
        self.add("help", script="1", level="4")
        self.assertEqual(self.last(), {"kind": "help", "script": 1, "level": 4})
        self.add("measure", target="wins", value="47.5")
        self.assertEqual(self.last(), {"kind": "measure", "target": "wins", "value": 47.5})
        self.add("reason", target="wins", text=" fun anyway ")
        self.assertEqual(self.last(), {"kind": "reason", "target": "wins", "text": "fun anyway"})
        self.add("rating", concept="ai", rating="can't yet")
        self.assertEqual(self.last(), {"kind": "rating", "concept": "ai", "rating": "can't yet"})
        self.add("note", text="the tests are slow")
        self.assertEqual(self.last(), {"kind": "note", "text": "the tests are slow"})

    def test_rejects_unknown_kind(self):
        self.assertIn("hint", self.rejects("hint", script=1))

    def test_rejects_level_5(self):
        for level in (5, 0, "5", "x", "1.5", True, ""):
            self.rejects("help", script=1, level=level)

    def test_rejects_unknown_script_target_and_concept(self):
        self.assertIn("9", self.rejects("help", script=9, level=1))
        self.assertIn("fun", self.rejects("measure", target="fun", value=1))
        self.rejects("reason", target="fun", text="x")

    def test_rating_of_unknown_concept(self):
        self.assertIn("sound", self.rejects("rating", concept="sound", rating="with help"))

    def test_rejects_unknown_rating(self):
        self.assertIn("on my own", self.rejects("rating", concept="ai", rating="good"))

    def test_rejects_missing_and_unknown_fields(self):
        self.assertIn("level", self.rejects("help", script=1))
        self.assertIn("who", self.rejects("help", script=1, level=1, who="x"))
        for text in ("", "   "):
            self.rejects("note", text=text)
            self.rejects("reason", target="wins", text=text)

    def test_rejects_values_that_are_no_number(self):
        for value in ("many", "nan", "inf", "", True):
            self.rejects("measure", target="wins", value=value)

    def tweak(self, predicted, before, after, **more):
        fields = dict(change="Moth.speed 4 to 5", predicted=predicted, target="wins", before=before, after=after)
        fields.update(more)
        return self.add("tweak", **fields)

    def test_tweak_direction_is_computed(self):
        cases = [("up", "40", "50", True), ("up", 50, 40, False), ("up", 40, 40, False), ("down", 50, 40, True),
                 ("down", 40, 50, False), ("none", 40, "40.0", True), ("none", 40, 41, False)]
        for predicted, before, after, right in cases:
            reply = self.tweak(predicted, before, after)
            entry = self.last()
            self.assertIs(entry["right"], right, (predicted, before, after))
            self.assertIn("right" if right else "wrong", reply)
        self.assertEqual(entry, {"kind": "tweak", "change": "Moth.speed 4 to 5", "predicted": "none",
                                 "target": "wins", "before": 40, "after": 41, "right": False})

    def test_tweak_is_checked(self):
        for bad in ({"predicted": "sideways"}, {"target": "fun"}, {"before": "x"}, {"change": " "}):
            with self.assertRaises(log.LogError):
                self.tweak(**dict({"predicted": "up", "before": 1, "after": 2}, **bad))
        self.rejects("tweak", change="x", predicted="up", target="wins", before=1, after=2, right=True)

    def test_the_sixth_tweak_says_so_and_later_ones_are_kept(self):
        replies = [self.tweak("up", 1, 2) for _ in range(7)]
        self.assertEqual([texts.TWEAKS_USED in r for r in replies], [False] * 5 + [True] * 2)
        self.assertEqual(len(self.data()["log"]), 7)

    def test_task_fills_tasks_done(self):
        self.add("task", part="1", index="2")
        self.add("task", part=2, index=1)
        self.add("task", part=1, index=2)   # twice is once
        self.assertEqual(self.data()["tasksDone"], [{"part": 0, "index": 1}, {"part": 1, "index": 0}])
        for part, index in ((3, 1), (0, 1), (1, 3), (1, 0), ("x", 1), (-1, 1)):
            self.rejects("task", part=part, index=index)

    def test_only_in_a_build(self):
        for status in ("planning", "done", "skipped"):
            self.make({"status": status})
            self.assertIn(status, self.rejects("note", text="x"))

    def test_missing_phase_and_latest_phase(self):
        with self.assertRaises(log.LogError):
            log.add(self.project, 9, "note", text="x")
        log.add(self.project, None, "note", text="x")
        self.assertEqual(self.last()["text"], "x")
        shutil.rmtree(self.project.docs)
        with self.assertRaises(log.LogError) as e:
            log.add(self.project, None, "note", text="x")
        self.assertIn("/start-phase 1", str(e.exception))

    def test_two_chats_at_once_lose_no_record(self):
        threads = [threading.Thread(target=self.add, args=("note",), kwargs={"text": str(i)}) for i in range(12)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sorted(int(e["text"]) for e in self.data()["log"]), list(range(12)))

    def test_status_reads_what_the_log_writes(self):
        self.add("help", script="1", level="3")
        self.add("measure", target="wins", value="50")
        self.add("rating", concept="ai", rating="with help")
        s = state.compute(self.project, 2)
        self.assertEqual((s.scripts[0].help, s.targets_met), (3, 1))
        self.assertEqual(s.wrap_items, [])


class CliTests(Base):
    def cli(self, *args, cwd=None):
        env = dict(os.environ, GIT_CEILING_DIRECTORIES=str(self.tmp.parent), PYTHONIOENCODING="cp1252")
        done = subprocess.run([sys.executable, str(LEARNING)] + list(args), cwd=str(cwd or self.tmp), env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL)
        self.assertEqual(done.stderr, b"")
        return done.returncode, done.stdout.decode("utf-8")

    def results_file(self, text):
        path = self.tmp / "out.csv"
        path.write_bytes(text.encode("utf-8"))
        os.utime(path, (helpers.FRESH, helpers.FRESH))
        return str(path)

    def test_status(self):
        self.make()
        for args in ((), ("2",), ("phase-2",), (" 2 ",)):
            code, out = self.cli("status", *args)
            self.assertEqual((code, out.split(" ")[:2]), (0, ["Phase", "2"]), args)
        code, out = self.cli("status", "abc")
        self.assertEqual(code, 1)
        self.assertIn("not a phase number", out)
        code, out = self.cli("status", "9")
        self.assertEqual(code, 1)
        self.assertIn("/start-phase", out)

    def test_status_from_a_subfolder(self):
        self.make()
        self.assertEqual(self.cli("status", cwd=self.tmp / "src")[0], 0)

    def test_status_without_a_phase(self):
        self.make(phases={})
        shutil.rmtree(self.tmp / "Docs")
        for args, code in (((), 0), (("2",), 0), (("abc",), 1)):
            got, out = self.cli("status", *args)
            self.assertEqual(got, code, args)
            self.assertIn("/start-phase 1", out)

    def test_no_project(self):
        for args in (("status",), ("log", "note", "text=x"), ("hand-over",), ("record-tests", "Unit", "x")):
            code, out = self.cli(*args)
            self.assertEqual(code, 1)
            self.assertIn("/setup-learning", out)
        self.assertEqual(list(self.tmp.iterdir()), [])

    def test_version_works_without_a_project(self):
        code, out = self.cli("version")
        self.assertEqual(code, 0)
        self.assertRegex(out, r"^\d+\.\d+\.\d+ [0-9a-f]{6}\n$")

    def test_log(self):
        self.make()
        code, out = self.cli("log", "note", "text=a = b, ü")
        self.assertEqual((code, self.data()["log"][0]["text"]), (0, "a = b, ü"), out)
        code, out = self.cli("log", "rating", "concept=ai", "rating=can't yet", "phase=2")
        self.assertEqual(code, 0, out)
        for args in (("help", "script=1", "level=5"), ("hint",), (), ("note", "text"), ("note", "text=a", "text=b"),
                     ("note", "text=a", "phase=x"), ("note", "text=a", "phase=9"), ("note", "kind=help", "text=a"),
                     ("note", "n=1", "text=a"), ("note", "project=1", "text=a")):
            code, out = self.cli("log", *args)
            self.assertEqual(code, 1, args)
            self.assertTrue(out.strip())
        self.assertEqual(len(self.data()["log"]), 2)

    def test_record_tests(self):
        self.make()
        path = self.results_file("MothTests.Turns,pass\nMothTests.Dies,fail\n")
        code, out = self.cli("record-tests", "Unit", path)
        self.assertEqual(code, 0, out)
        self.assertIn("1 passed, 1 failed", out)
        self.assertEqual(self.data()["results"]["Unit"]["tests"],
                         {"MothTests.Turns": "passed", "MothTests.Dies": "failed"})
        self.assertEqual(self.cli("record-tests", "Unit", "out.csv", "phase=2")[0], 0)
        for args in (("Play", path), ("Unit", "missing.xml"), ("Unit",), (), ("Unit", path, "phase=9"),
                     ("Unit", path, "more")):
            code, out = self.cli("record-tests", *args)
            self.assertEqual(code, 1, args)
            self.assertTrue(out.strip())
        self.make({"status": "done"})
        self.assertEqual(self.cli("record-tests", "Unit", path)[0], 1)
        self.assertNotIn("results", self.data())

    def test_hand_over(self):
        files = dict(TEST_CODE, **{"src/Moth.cs": shell(["1.1", "1.2"]), "src/Lamp.cs": shell(["2.1"])})
        self.make({"turn": "ai"}, files=files)
        code, out = self.cli("hand-over")
        self.assertEqual(code, 1)
        self.assertIn(texts.suite_not_recorded("Unit"), out)
        path = self.results_file("MothTests.Turns,fail\nMothTests.Dies,fail\nLampTests.Glows,fail\nOther.A,pass\n")
        self.cli("record-tests", "Unit", path)
        code, out = self.cli("hand-over", "2")
        self.assertEqual((code, out), (0, "Phase 2, part 1 handed over. Your turn: 2 scripts, 3 TODOs.\n"
                                          "Next: open a new chat and type /summarize-phase 2\n"))
        self.assertEqual(self.cli("hand-over", "abc")[0], 1)

    def test_broken_files_are_messages(self):
        self.make()
        self.project.state_path(2).write_bytes(b'{\n"status" "build"}')
        for args in (("status",), ("log", "note", "text=x"), ("hand-over",)):
            code, out = self.cli(*args)
            self.assertEqual(code, 1)
            self.assertIn("phase-2.json", out)
            self.assertIn("line 2", out)
        (self.tmp / ".claude" / "learning" / "project.json").write_bytes(b"{")
        code, out = self.cli("status")
        self.assertEqual(code, 1)
        self.assertIn("project.json", out)

    def test_a_plan_of_wrong_types_is_one_line_and_no_traceback(self):
        self.make({"turn": "ai"}, files={"src/Moth.cs": shell(["1.1", "1.2"])})
        p = full_plan(parts=TWO_PARTS)
        p["scripts"][0]["tests"] = [None]
        bad_tests = dict(p)
        for plan_, args in ((bad_tests, ("hand-over",)), (dict(full_plan(), targets=None), ("status",)),
                            (dict(full_plan(), targets=[7]), ("log", "measure", "target=wins", "value=1")),
                            (dict(full_plan(), scripts="x"), ("hand-over",))):
            helpers.write_json(self.project.plan_path(2), plan_)
            code, out = self.cli(*args)   # cli() also checks that stderr is empty
            self.assertEqual((code, len(out.splitlines())), (1, 1), out)
            self.assertIn("guided-learning error: ", out)

    def test_unknown_command_prints_the_usage(self):
        for args in ((), ("frobnicate",)):
            code, out = self.cli(*args)
            self.assertEqual(code, 1)
            self.assertIn("record-tests", out)

    def test_the_cli_works_on_the_rehearsal(self):
        self.make()
        rehearsal = self.tmp / ".claude" / "learning" / "rehearsal"
        helpers.make_project(rehearsal, phases={4: {"state": {"status": "planning"}}})
        helpers.set_switch(self.tmp, '{"rehearsal": true}')
        self.assertTrue(self.cli("status")[1].startswith("Phase 4 - planning"))


class RecordCheckTests(Base):
    def test_record_returns_the_tests_and_checks_inside_the_update(self):
        self.make()
        path = self.tmp / "out.csv"
        path.write_bytes(b"A.b,pass\n")
        self.assertEqual(results.record(self.project, 2, "Unit", str(path)), {"A.b": "passed"})

        def refuse(data):
            raise log.LogError("no")

        before = self.project.state_path(2).read_bytes()
        with self.assertRaises(log.LogError):
            results.record(self.project, 2, "Unit", str(path), refuse)
        self.assertEqual(self.project.state_path(2).read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
