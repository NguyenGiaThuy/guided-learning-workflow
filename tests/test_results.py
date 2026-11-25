import os
import tempfile
import unittest
from pathlib import Path

from helpers import make_project
from gl import project, results, state, store, texts

DATA = Path(__file__).resolve().parent / "data"
_FULL = {"LanternKeeper.MothTests.Turns": "passed", "LanternKeeper.MothTests.FliesToLight": "passed",
         "LanternKeeper.MothTests.Dies": "failed", "LanternKeeper.MothTests.Sleeps": "skipped"}
EXPECT = {
    "nunit.xml": _FULL,
    "junit.xml": _FULL,
    "plain.csv": {"MothTests.Turns": "passed", "MothTests.FliesToLight": "passed", "MothTests.Dies": "failed"},
}


class ParseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def write(self, name, data):
        p = Path(self.tmp.name) / name
        p.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
        return p

    def test_nunit(self):
        self.assertEqual(results.parse(DATA / "nunit.xml"), EXPECT["nunit.xml"])

    def test_junit(self):
        self.assertEqual(results.parse(DATA / "junit.xml"), EXPECT["junit.xml"])

    def test_plain(self):
        self.assertEqual(results.parse(DATA / "plain.csv"), EXPECT["plain.csv"])

    def test_detected_by_content_and_bom(self):
        p = self.write("whatever.txt", b"\xef\xbb\xbf" + (DATA / "junit.xml").read_bytes())
        self.assertEqual(results.parse(p), EXPECT["junit.xml"])
        p = self.write("x.xml", "A.b,passed\r\nA.c,Failed\r\n")
        self.assertEqual(results.parse(p), {"A.b": "passed", "A.c": "failed"})

    def test_nunit_variants(self):
        p = self.write("n.xml", '<test-results><test-case name="A" result="Inconclusive"/>'
                       '<test-case name="B" result="Failed" label="Error"/></test-results>')
        self.assertEqual(results.parse(p), {"A": "skipped", "B": "failed"})

    def test_junit_error_child_and_bare_name(self):
        p = self.write("j.xml", '<testsuite><testcase name="A"><error/></testcase></testsuite>')
        self.assertEqual(results.parse(p), {"A": "failed"})

    def test_errors_name_file_and_line(self):
        p = self.write("bad.xml", "<testsuite><testcase")
        with self.assertRaises(results.ResultError) as c:
            results.parse(p)
        self.assertIn("bad.xml", str(c.exception))
        p = self.write("bad.csv", "A,pass\nnonsense\n")
        with self.assertRaises(results.ResultError) as c:
            results.parse(p)
        self.assertIn("bad.csv", str(c.exception))
        self.assertIn("2", str(c.exception))
        p = self.write("other.xml", "<html/>")
        with self.assertRaises(results.ResultError):
            results.parse(p)

    def test_matches(self):
        self.assertTrue(results.matches("MothTests.Turns", "MothTests.Turns"))
        self.assertTrue(results.matches("MothTests.Turns", "LanternKeeper.MothTests.Turns(1,2)"))
        self.assertTrue(results.matches("Turns", "LanternKeeper.MothTests.Turns"))
        self.assertFalse(results.matches("Turns", "LanternKeeper.MothTests.ReTurns"))
        self.assertFalse(results.matches("MothTests.Turns", "MothTests.Turn"))


class RecordTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = make_project(self.tmp.name, {2: {"state": {"status": "build"}}})
        self.proj = project.find(root)
        self.code = Path(root) / "src" / "Moth.cs"
        self.code.write_text("class Moth {}")
        os.utime(self.code, (1000, 1000))

    def result_file(self, name, text, mtime):
        p = Path(self.tmp.name) / name
        p.write_text(text)
        os.utime(p, (mtime, mtime))
        return p

    def state(self):
        return store.read(self.proj.state_path(2))

    def test_record_stores_passed_and_failed_with_file_time(self):
        results.record(self.proj, 2, "Unit", DATA / "plain.csv")
        r = self.state()["results"]["Unit"]
        self.assertEqual(r["tests"], {k: v for k, v in EXPECT["plain.csv"].items()})
        self.assertEqual(r["time"], os.stat(DATA / "plain.csv").st_mtime)

    def test_skipped_not_stored(self):
        results.record(self.proj, 2, "Unit", DATA / "junit.xml")
        self.assertNotIn("LanternKeeper.MothTests.Sleeps", self.state()["results"]["Unit"]["tests"])

    def test_unknown_suite_is_refused(self):
        with self.assertRaises(results.ResultError) as c:
            results.record(self.proj, 2, "Play", DATA / "plain.csv")
        self.assertIn("Play", str(c.exception))
        self.assertNotIn("results", self.state())

    def test_empty_or_all_skipped_is_refused(self):
        e = self.result_file("e.csv", "\n\n", 2000)
        s = self.result_file("s.xml", '<testsuite><testcase name="A"><skipped/></testcase></testsuite>', 2000)
        for p in (e, s):
            with self.assertRaises(results.ResultError) as c:
                results.record(self.proj, 2, "Unit", p)
            self.assertIn("smoke test", str(c.exception))
        self.assertNotIn("results", self.state())

    def test_fresh_results_are_merged(self):
        a = self.result_file("a.csv", "A,pass\nB,fail\n", 3000)
        b = self.result_file("b.csv", "B,pass\nC,pass\n", 4000)
        results.record(self.proj, 2, "Unit", a)
        results.record(self.proj, 2, "Unit", b)
        r = self.state()["results"]["Unit"]
        self.assertEqual(r["tests"], {"A": "passed", "B": "passed", "C": "passed"})
        self.assertEqual(r["time"], 3000)

    def test_stale_results_are_replaced(self):
        a = self.result_file("a.csv", "A,pass\nB,fail\n", 3000)
        results.record(self.proj, 2, "Unit", a)
        os.utime(self.code, (5000, 5000))   # code changed after the stored results
        b = self.result_file("b.csv", "C,pass\n", 6000)
        results.record(self.proj, 2, "Unit", b)
        r = self.state()["results"]["Unit"]
        self.assertEqual(r["tests"], {"C": "passed"})
        self.assertEqual(r["time"], 6000)

    def test_the_names_a_suite_has_had_are_kept(self):
        a = self.result_file("a.csv", "Game.A.x(1),pass\nGame.A.x(2),fail\nB.y,pass\n", 3000)
        results.record(self.proj, 2, "Unit", a)
        self.assertEqual(self.state()["results"]["Unit"]["known"], ["B.y", "Game.A.x"])
        os.utime(self.code, (5000, 5000))
        results.record(self.proj, 2, "Unit", self.result_file("b.csv", "C.z,pass\n", 6000))
        r = self.state()["results"]["Unit"]
        self.assertEqual((r["tests"], r["known"]), ({"C.z": "passed"}, ["B.y", "C.z", "Game.A.x"]))
        results.record(self.proj, 2, "Unit", self.result_file("c.csv", "D.w,pass\n", 7000))
        self.assertEqual(self.state()["results"]["Unit"]["known"], ["B.y", "C.z", "D.w", "Game.A.x"])

    def test_the_names_of_results_from_before_are_kept(self):
        for odd in ({}, {"known": 5}, {"known": [5, None]}):
            entry = dict({"time": 1, "tests": {"A.x": "passed"}}, **odd)
            self.proj.update_state(2, lambda d: {"status": "build", "results": {"Unit": entry}})
            results.record(self.proj, 2, "Unit", self.result_file("b.csv", "B.y,pass\n", 6000))
            self.assertEqual(self.state()["results"]["Unit"]["known"], ["A.x", "B.y"])

    def items(self, code, *runs, **kw):
        """The suite items after the code was saved and the runs of one suite were recorded."""
        for time, text in runs:
            results.record(self.proj, 2, "Unit", self.result_file("r.csv", text, time))
        self.code.write_text(code)
        os.utime(self.code, (kw.pop("saved", 1000),) * 2)
        return state.suite_items(self.proj, self.state(), **kw)

    ALL = "Game.A.x(1),pass\nA.y,pass\nB.z,pass\n"

    def test_a_filtered_run_after_a_change_is_not_the_whole_suite(self):
        code = "class A { void x() {} void y() {} } class B { void z() {} }"
        item = texts.suite_not_run("Unit", ["A.y", "B.z"])
        self.assertEqual(item, "Suite Unit: 2 tests not run since the last code change: A.y, B.z. Run the whole suite and "
                               "record it. A test that was removed or renamed must be gone from the code. An ignored "
                               "test is seen when the result file of the whole suite reports it.")
        os.utime(self.code, (1000, 1000))
        results.record(self.proj, 2, "Unit", self.result_file("a.csv", self.ALL, 3000))
        os.utime(self.code, (5000, 5000))
        self.assertEqual(self.items(code, (6000, "A.x,pass\n"), saved=5000), [item])
        self.assertEqual(self.items(code, (6000, "A.x,pass\n"), saved=5000, leave_out=["A.y"]),
                         [texts.suite_not_run("Unit", ["B.z"])])
        self.assertEqual(self.items(code, saved=5000, covered=["A.y", "B.z"]), [])
        self.assertEqual(self.items(code, (6500, "A.y,pass\nB.z,pass\n"), saved=5000), [])
        self.assertEqual(self.items(code, saved=9000), [texts.suite_old("Unit")])

    def test_names_that_are_gone_from_the_code_do_not_count(self):
        results.record(self.proj, 2, "Unit", self.result_file("a.csv", self.ALL, 3000))
        os.utime(self.code, (5000, 5000))
        self.assertEqual(self.items("class A { void x() {} void yy() {} }", (6000, "A.x,pass\n"), saved=5000), [])

    def test_a_test_that_moved_counts_as_run(self):
        results.record(self.proj, 2, "Unit", self.result_file("a.csv", self.ALL, 3000))
        os.utime(self.code, (5000, 5000))
        code = "class A { void x() {} void y() {} } class B { void z() {} }"
        moved = "New.A.x(7),pass\nNew.A.y,pass\nB.z,pass\n"   # another case and another namespace
        self.assertEqual(self.items(code, (6000, moved), saved=5000), [])
        self.proj.settings["suites"] = ["Unit", "Play"]   # and into another suite
        results.record(self.proj, 2, "Play", self.result_file("b.csv", "A.y,pass\n", 6000))
        self.proj.update_state(2, lambda d: d["results"]["Unit"]["tests"].pop("New.A.y") and None)
        self.assertEqual(state.suite_items(self.proj, self.state()), [])

    def changed(self, code, *runs):
        """The suite items after all tests ran, the code changed, and then these runs."""
        results.record(self.proj, 2, "Unit", self.result_file("a.csv", self.ALL, 3000))
        os.utime(self.code, (5000, 5000))
        return self.items(code, *runs, saved=5000)

    def test_a_renamed_test_is_gone_although_its_old_name_is_called(self):
        code = "class A { void x() { g.y(); } void yNew() { var r = g.y(); return y(); } }\nclass B { void z() {} }"
        self.assertEqual(self.changed(code, (6000, "A.x,pass\nA.yNew,pass\nB.z,pass\n")), [])
        self.assertIn("A.y", self.state()["results"]["Unit"]["known"])
        self.assertEqual(self.items(code.replace("yNew", "y"), saved=5000),   # declared again, and so listed again
                         [texts.suite_not_run("Unit", ["A.y"])])

    def test_a_removed_test_is_gone(self):
        code = "class A { void x() {}\n// void y() {}\n}\nclass B { void z() {} }"
        self.assertEqual(self.changed(code, (6000, "A.x,pass\n")), [texts.suite_not_run("Unit", ["B.z"])])
        self.assertEqual(self.items(code, (6500, "B.z,pass\n"), saved=5000), [])

    CODE = "class A { void x() {} void y() {} } class B { void z() {} }"

    @staticmethod
    def xml(**outcomes):
        """A JUnit file; A_x means the test x of class A."""
        kids = {"pass": "", "fail": "<failure/>", "skip": "<skipped/>"}
        return "<testsuite>%s</testsuite>" % "".join(
            '<testcase classname="Game.%s" name="%s">%s</testcase>' % (k[0], k[2:], kids[v]) for k, v in outcomes.items())

    def skipped(self):
        return self.state()["results"]["Unit"].get("skipped")

    def test_a_skipped_test_counts_as_seen(self):
        self.assertEqual(self.changed(self.CODE, (6000, self.xml(A_x="pass", A_y="skip", B_z="pass"))), [])
        entry = self.state()["results"]["Unit"]
        self.assertEqual((entry["skipped"], entry["tests"]),
                         (["Game.A.y"], {"Game.A.x": "passed", "Game.B.z": "passed"}))

    def test_a_skipped_test_hides_no_other(self):
        self.assertEqual(self.changed(self.CODE, (6000, self.xml(A_x="pass", A_y="skip"))),
                         [texts.suite_not_run("Unit", ["B.z"])])

    def test_a_skipped_test_of_an_old_file_is_not_seen(self):
        self.changed(self.CODE, (6000, self.xml(A_x="pass", A_y="skip", B_z="pass")))
        os.utime(self.code, (7000, 7000))
        self.assertEqual(self.items(self.CODE, (8000, self.xml(A_x="pass", B_z="pass")), saved=7000),
                         [texts.suite_not_run("Unit", ["A.y"])])
        self.assertEqual(self.skipped(), [])

    def test_skipped_names_are_merged_and_taken_out_by_a_result(self):
        self.changed(self.CODE, (6000, self.xml(A_x="pass", A_y="skip")), (6100, self.xml(A_x="pass", B_z="skip")))
        self.assertEqual(self.skipped(), ["Game.A.y", "Game.B.z"])
        self.items(self.CODE, (6200, self.xml(A_y="pass", B_z="fail")), saved=5000)
        self.assertEqual(self.skipped(), [])
        self.assertEqual(self.state()["results"]["Unit"]["tests"],
                         {"Game.A.x": "passed", "Game.A.y": "passed", "Game.B.z": "failed"})

    def test_a_later_skip_hides_no_result(self):
        items = self.changed(self.CODE, (6000, self.xml(A_x="pass", A_y="fail", B_z="pass")),
                             (6100, self.xml(A_x="skip", A_y="skip", B_z="pass")))
        self.assertEqual(items, [texts.suite_failing("Unit", ["Game.A.y"])])
        self.assertEqual(self.skipped(), [])

    def test_damaged_skipped_names_count_as_none(self):
        self.changed(self.CODE, (6000, self.xml(A_x="pass", B_z="pass")))
        for odd in (5, "Game.A.y", [5, None], {"Game.A.y": 1}):
            self.proj.update_state(2, lambda d: d["results"]["Unit"].update(skipped=odd))
            self.assertEqual(state.suite_items(self.proj, self.state()), [texts.suite_not_run("Unit", ["A.y"])], odd)
        results.record(self.proj, 2, "Unit", self.result_file("b.xml", self.xml(A_x="pass", A_y="skip"), 6100))
        self.assertEqual(self.skipped(), ["Game.A.y"])

    def test_many_names_are_cut(self):
        names = ["A.t%d" % i for i in range(9)]
        self.assertTrue(texts.suite_not_run("Unit", names).startswith(
            "Suite Unit: 9 tests not run since the last code change: A.t0, A.t1, A.t2, A.t3, A.t4 and 4 more. Run "))
        self.assertIn("1 test not run", texts.suite_not_run("Unit", names[:1]))

    def test_result_older_than_code_is_not_fresh(self):
        old = self.result_file("old.csv", "A,pass\n", 500)
        results.record(self.proj, 2, "Unit", old)     # recorded, but not fresh
        self.assertFalse(results.fresh(self.proj, self.state(), "Unit"))

    def test_old_file_merged_into_fresh_makes_it_not_fresh(self):
        # time = min(old, new): an old file merged in drags the time back, so the suite
        # is no longer fresh, instead of passing for a run made after the last code change.
        a = self.result_file("a.csv", "A,pass\n", 3000)
        old = self.result_file("old.csv", "B,pass\n", 500)
        results.record(self.proj, 2, "Unit", a)
        self.assertTrue(results.fresh(self.proj, self.state(), "Unit"))
        results.record(self.proj, 2, "Unit", old)
        self.assertEqual(self.state()["results"]["Unit"]["time"], 500)
        self.assertFalse(results.fresh(self.proj, self.state(), "Unit"))

    def test_equal_time_counts_as_fresh(self):
        # A run saved in the same instant as the code (file times tick coarsely) is given
        # the benefit of the doubt; demanding strictly newer would reject honest runs.
        p = self.result_file("p.csv", "A,pass\n", 1000)
        results.record(self.proj, 2, "Unit", p)
        self.assertTrue(results.fresh(self.proj, self.state(), "Unit"))

    def test_fresh_without_results(self):
        self.assertFalse(results.fresh(self.proj, {}, "Unit"))
        self.assertFalse(results.fresh(self.proj, {"results": {}}, "Unit"))


if __name__ == "__main__":
    unittest.main()
