import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import helpers
from helpers import FULL_MD, OLD, TEST_CODE, full_plan, shell, suite_result
from gl import commands, markdown, project, render, scorecard, state, texts

PASSED = {t: "passed" for s in full_plan()["scripts"] for t in s["tests"]}
LOG = [{"kind": "measure", "target": "wins", "value": 50},
       {"kind": "rating", "concept": "ai", "rating": "with help"}]
CODE = dict({"src/%s.cs" % n: shell([]) for n in ("Moth", "Lamp", "Keeper")}, **TEST_CODE)


def row(text, name):
    return [x for x in text.splitlines() if x.startswith(name + ":")][0]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        for name, fn in (("current_branch", lambda p: "stage-2"), ("is_merged", lambda p, b: True)):
            patcher = mock.patch.object(state, name, side_effect=fn)
            patcher.start()
            self.addCleanup(patcher.stop)

    def phase(self, stored=None, md=FULL_MD, n=2):
        st = {"status": "build", "branch": "stage-2", "turn": "owner", "part": 0, "log": LOG,
              "results": {"Unit": suite_result(PASSED)}}
        st.update(stored or {})
        return {"state": st, "plan": full_plan(n), "md": md}

    def make(self, phases):
        self.project = project.find(helpers.make_project(self.tmp, phases=phases, files=CODE))
        return self.project

    def card(self, stored=None, md=FULL_MD):
        return scorecard.compute(self.make({2: self.phase(stored, md)}), 2)


class RowTests(Base):
    def test_build_row(self):
        helps = [{"kind": "help", "script": 1, "level": 1}, {"kind": "help", "script": 1, "level": 3},
                 {"kind": "help", "script": 2, "level": 2}]
        passed = dict(PASSED, **{"MothTests.Dies": "failed"})
        card = self.card({"log": LOG + helps, "results": {"Unit": suite_result(passed)}})
        self.assertEqual((card["build"]["passing"], card["build"]["total"]), (2, 3))
        self.assertEqual(card["build"]["help"], {"Owner 1 Moth": 3, "Owner 2 Lamp": 2, "Owner 3 Keeper": 0})

    def test_predict_row_counts_right_direction(self):
        tweaks = [{"kind": "tweak", "predicted": "up", "right": True},
                  {"kind": "tweak", "predicted": "up", "right": False},
                  {"kind": "tweak", "predicted": "none", "right": True}]
        card = self.card({"log": LOG + tweaks})
        self.assertEqual((card["predict"]["right"], card["predict"]["total"]), (2, 3))
        self.assertEqual(self.card()["predict"], {"right": 0, "total": 0})

    def test_balance_row(self):
        card = self.card()
        self.assertEqual((card["balance"]["met"], card["balance"]["total"]), (1, 1))
        miss = self.card({"log": [{"kind": "measure", "target": "wins", "value": 90}]})
        self.assertEqual(miss["balance"]["met"], 0)

    def test_explain_row(self):
        self.assertEqual(self.card()["explain"], {"Enemy AI": "with help"})
        self.assertEqual(self.card({"log": []})["explain"], {"Enemy AI": texts.NOT_RATED})

    def test_process_row(self):
        self.assertEqual(self.card()["process"],
                         {"surprised": "the tests came first", "differently": "start smaller"})

    def test_done_phase_ignores_stale_results(self):
        old = {"results": {"Unit": suite_result(PASSED, OLD)}}
        self.assertEqual(self.card(old)["build"]["passing"], 0)
        self.assertEqual(self.card(dict(old, status="done"))["build"]["passing"], 3)


class NoTuningTests(Base):
    def test_no_balance_or_predict_line_without_targets_and_tweaks(self):
        ph = self.phase({"log": [{"kind": "rating", "concept": "ai", "rating": "with help"}]})
        ph["plan"]["targets"] = []
        text = scorecard.render(self.make({2: ph}), 2)
        self.assertFalse([x for x in text.splitlines() if x.startswith(("Balance:", "Predict:"))], text)
        self.assertIn("Build:", text)

    def test_lines_stay_with_targets(self):
        root = helpers.make_project(self.tmp, phases={2: self.phase()}, files=CODE, settings={"tuning": False})
        text = scorecard.render(project.find(root), 2)
        self.assertIn(texts.score_balance(1, 1, texts.DEFAULT_WORDS), text)
        self.assertIn(texts.score_predict(0, 0), text)

    def test_a_tweak_keeps_the_predict_line(self):
        ph = self.phase({"log": [{"kind": "tweak", "predicted": "up", "right": True}]})
        ph["plan"]["targets"] = []
        self.assertIn(texts.score_predict(1, 1), scorecard.render(self.make({2: ph}), 2))


class TrendTests(Base):
    def two(self, previous):
        return scorecard.render(self.make({1: self.phase(previous, n=1), 2: self.phase()}), 2)

    def test_trend_shows_last_phase_value(self):
        passed = {k: ("passed" if k.startswith("MothTests") else "failed") for k in PASSED}
        text = self.two({"status": "done", "results": {"Unit": suite_result(passed, OLD)}})
        self.assertIn("(last phase: 1/3)", row(text, "Build"))
        self.assertIn("(last phase: 0/0)", row(text, "Predict"))
        self.assertIn("(last phase: 1/1)", row(text, "Balance"))
        self.assertNotIn("last phase", row(text, "Explain") + row(text, "Process"))

    def test_no_previous_phase_no_trend(self):
        self.assertNotIn("last phase", scorecard.render(self.make({2: self.phase()}), 2))
        self.assertNotIn("last phase", self.two({"status": "build"}))   # the phase before is not done

    def test_one_row_per_line_and_no_grade(self):
        lines = scorecard.render(self.make({2: self.phase()}), 2).splitlines()
        self.assertEqual([x.split(":")[0] for x in lines[1:]], ["Build", "Predict", "Balance", "Explain", "Process"])
        self.assertEqual(lines[0], texts.scorecard_heading(2))
        self.assertIn("Owner 1 Moth none", lines[1])


class StatusTests(Base):
    def test_wrap_up_status_shows_scorecard_when_nothing_open(self):
        proj = self.make({2: self.phase()})
        text = render.status(state.compute(proj, 2))
        self.assertTrue(text.startswith("Phase 2 - wrap-up "))
        self.assertIn(scorecard.render(proj, 2), text)
        self.assertTrue(text.endswith(texts.next_line("finish-phase", 2) + "\n"))
        open_ = render.status(state.compute(self.make({2: self.phase(md=FULL_MD.replace("- one\n", ""))}), 2))
        self.assertNotIn(texts.scorecard_heading(2), open_)

    def test_done_status_shows_summary_lessons_scorecard(self):
        proj = self.make({2: self.phase({"status": "done"})})
        text = render.status(state.compute(proj, 2))
        for part in (texts.done_text(2), texts.SUMMARY_HEADING, "Enemy AI", "A state machine with two states.",
                     texts.LESSONS_HEADING, "- one", "- three", scorecard.render(proj, 2)):
            self.assertIn(part, text)
        self.assertTrue(text.endswith(texts.next_line("start-phase", 3) + "\n"))


class FinishTests(Base):
    def finish(self):
        out = commands.run(self.project, "finish", "2")
        self.assertTrue(out.ok, out.text)
        return out.text

    def read(self):
        return self.project.md_path(2).read_bytes().decode("utf-8")

    def test_finish_writes_scorecard_once(self):
        self.make({2: self.phase()})
        text = self.finish()
        md = self.read()
        self.assertTrue(md.startswith(FULL_MD), "hand-written text is unchanged")
        self.assertEqual(md.count("## Scorecard"), 1)
        self.assertTrue(md.endswith(scorecard.render(self.project, 2).split("\n", 1)[1] + "\n"))
        self.assertIn("Phase 2 is done.", text)
        self.finish()
        self.assertEqual(self.read(), md)
        self.assertEqual(len(markdown.load(self.project.md_path(2)).lessons), 3)   # the section is ignored

    def test_done_phase_without_scorecard_gets_it_once(self):
        self.make({2: self.phase({"status": "done"})})
        self.finish()
        self.finish()
        self.assertEqual(self.read().count("## Scorecard"), 1)

    def test_refused_finish_writes_no_scorecard(self):
        self.make({2: self.phase({"log": []})})
        self.assertFalse(commands.run(self.project, "finish", "2").ok)
        self.assertNotIn("Scorecard", self.read())

    def test_crlf_file_keeps_its_bytes(self):
        raw = FULL_MD.replace("\n", "\r\n")
        self.make({2: self.phase(md=raw)})
        self.finish()
        data = self.project.md_path(2).read_bytes()
        self.assertTrue(data.startswith(raw.encode("utf-8")))
        self.assertNotIn(b"\n", data.replace(b"\r\n", b""))


if __name__ == "__main__":
    unittest.main()
