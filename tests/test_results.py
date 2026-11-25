import os
import tempfile
import unittest
from pathlib import Path

from helpers import make_project
from gl import project, results, store

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
            with self.assertRaises(results.ResultError):
                results.record(self.proj, 2, "Unit", p)
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
