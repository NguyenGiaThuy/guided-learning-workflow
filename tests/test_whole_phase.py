"""A whole phase through the real hooks and command line, in a real git repository."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

import helpers
from helpers import FULL_MD, TEST_CODE, full_plan, shell
from gl import store, texts

LEARNING = Path(__file__).resolve().parent.parent / "scripts" / "learning.py"
MARK = '[Explicit("Owner")] '
OWNER = [t for s in full_plan()["scripts"] for t in s["tests"]]
SHELLS = {"src/Moth.cs": ["1.1", "1.2"], "src/Lamp.cs": ["2.1"], "src/Keeper.cs": ["3.1"]}
GAME_TESTS = {"src/GameTests.cs": "class GameTests { void Starts() {} void Ends() {} }\n"}


@unittest.skipUnless(shutil.which("git"), "git is not available")
class WholePhaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(os.path.realpath(tempfile.mkdtemp()))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = self.tmp / "game"
        self.root.mkdir()
        self.clock = time.time() - 10000   # files and results get their times in this order
        settings = self.tmp / "settings.json"
        helpers.write_json(settings, helpers.PROJECT_JSON)
        self.cli("setup", str(settings))
        (self.root / "src").mkdir()
        self.git("init", "-q")
        self.commit()
        self.git("branch", "-q", "-M", "main")

    # --- the game, the owner, the AI ---

    def run_(self, *args, **kw):
        env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
        return subprocess.run([sys.executable, str(LEARNING)] + list(args), cwd=str(self.root), env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kw)

    def cli(self, *args, ok=True):
        done = self.run_(*args, stdin=subprocess.DEVNULL)
        text = done.stdout.decode("utf-8")
        self.assertEqual((done.returncode, done.stderr), (0 if ok else 1, b""), text)
        return text

    def hook(self, event, **data):
        data.setdefault("cwd", str(self.root))
        done = self.run_("hook", event, input=json.dumps(data).encode("utf-8"))
        self.assertEqual((done.returncode, done.stderr), (0, b""))
        return json.loads(done.stdout.decode("utf-8")) if done.stdout else None

    def typed(self, prompt):
        out = self.hook("UserPromptSubmit", prompt=prompt, session_id="s1")
        self.assertNotIn("decision", out, out)
        return out["hookSpecificOutput"]["additionalContext"]

    def blocked(self, prompt):
        out = self.hook("UserPromptSubmit", prompt=prompt, session_id="s1")
        self.assertEqual(out.get("decision"), "block", out)
        return out["reason"]

    def ai_may_write(self, name):
        out = self.hook("PreToolUse", tool_name="Write", tool_use_id="t1",
                        tool_input={"file_path": str(self.root / name), "content": "class X {}\n"})
        self.assertTrue(out is None or out["hookSpecificOutput"]["permissionDecision"] == "deny")
        return out is None

    def git(self, *args):
        return helpers.git(self.root, *args)

    def commit(self):
        helpers.commit(self.root)

    def tick(self):
        self.clock += 10
        return self.clock

    def save(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
        os.utime(path, (self.tick(),) * 2)

    def record(self, passed=(), failed=()):
        """A run of the suite that has just ended. Returns what the command line says."""
        path = self.tmp / "results.csv"
        path.write_text("".join("%s,pass\n" % t for t in passed) + "".join("%s,fail\n" % t for t in failed))
        os.utime(path, (self.tick(),) * 2)
        return self.cli("record-tests", "Unit", str(path))

    def touch_code(self):
        """Git gives a file the time of the switch; that is no change of the code."""
        for path in (self.root / "src").rglob("*.cs"):
            if os.stat(path).st_mtime > self.clock:
                os.utime(path, (self.clock,) * 2)

    def switch(self, *args):
        self.git("switch", "-q", *args)
        self.touch_code()

    def data(self, n=1):
        return store.read(self.root / "Docs" / "learning" / ("phase-%d.json" % n))

    def plan(self, n=1):
        helpers.write_json(self.root / "Docs" / "learning" / ("phase-%d.plan.json" % n), full_plan(n))

    # --- the steps ---

    def built(self):
        """Phase 1 is planned, approved and built on stage-1, and handed over."""
        self.switch("-c", "stage-1")
        self.assertTrue(self.typed("/start-phase 1").endswith(texts.next_line("approve-phase", 1)))
        self.assertTrue(self.typed("/summarize-phase").endswith(texts.next_line("start-phase", 1)))
        self.assertTrue(self.blocked("/approve-phase 1").endswith(texts.next_line("start-phase", 1)))
        self.plan()
        self.assertFalse(self.ai_may_write("src/Moth.cs"))
        self.assertTrue(self.typed("/summarize-phase").endswith(texts.next_line("approve-phase", 1)))
        self.assertTrue(self.typed("/approve-phase 1").endswith(texts.next_line("build-phase", 1)))
        self.assertIn("it is the AI's turn", self.typed("/build-phase"))
        self.assertTrue(self.ai_may_write("src/Moth.cs"))
        for name, todos in SHELLS.items():
            self.save(name, shell(todos))
        for name, text in dict(TEST_CODE, **GAME_TESTS).items():
            self.save(name, text.replace("void", MARK + "void") if name in TEST_CODE else text)
        self.cli("log", "task", "part=1", "index=1")
        self.record(["GameTests.Starts", "GameTests.Ends"], OWNER)
        self.assertIn("handed over. Your turn: 3 scripts, 4 TODOs.", self.cli("hand-over", "1"))
        self.commit()

    def played(self):
        """The owner has written everything, tuned and answered."""
        for name in SHELLS:
            self.save(name, shell([]))
        for name, text in TEST_CODE.items():
            self.save(name, text)
        self.record(OWNER + ["GameTests.Starts", "GameTests.Ends"])
        self.assertIn("Phase 1 - tune", self.typed("/summarize-phase 1"))
        self.cli("log", "measure", "target=wins", "value=50")
        self.cli("log", "rating", "concept=ai", "rating=with help")
        self.save("Docs/learning/phase-1.md", FULL_MD.replace("Phase 2", "Phase 1"))

    # --- the tests ---

    def test_a_whole_phase(self):
        self.built()
        wrong = texts.wrong_branch("stage-1", "main")

        self.switch("main")   # in the middle: the phase files are not here
        for prompt in ("/summarize-phase", "/summarize-phase 1"):
            self.assertIn(wrong, self.typed(prompt))
        self.assertIn(wrong, self.cli("status", "1"))
        for prompt in ("/start-phase 1", "/start-phase 2", "/approve-phase 1", "/build-phase", "/finish-phase 1"):
            self.assertIn(wrong, self.blocked(prompt))
        self.assertFalse(self.ai_may_write("src/Moth.cs"))
        self.assertTrue(self.ai_may_write("src/Other.cs"))
        self.assertEqual(self.git("status", "--porcelain"), "")

        self.switch("stage-1")
        self.assertIn("0 of 4 TODOs done", self.typed("/summarize-phase 1"))
        self.assertFalse(self.ai_may_write("src/Moth.cs"))
        self.assertIn(texts.owners_turn(1, 0), self.blocked("/build-phase 1"))
        self.played()
        self.assertTrue(self.typed("/summarize-phase 1").endswith(texts.next_line("finish-phase", 1)))
        self.commit()

        text = self.typed("/finish-phase 1")
        self.assertEqual(text, "Phase 1 is done. Saved in Docs/learning/phase-1.md.\n"
                               "Branch stage-1: not merged.\n"
                               "Carried to phase 2: Enemy AI | start smaller\n"
                               "Next: commit, merge the branch, then open a new chat and type /start-phase 2")
        self.assertEqual(self.hook("Stop", last_assistant_message="Done.")["decision"], "block")
        self.assertIsNone(self.hook("Stop", last_assistant_message="Done.\n" + text))
        changed = [line[3:].strip() for line in self.git("status", "--porcelain").splitlines()]
        self.assertEqual(sorted(changed), ["Docs/learning/phase-1.json", "Docs/learning/phase-1.md"])

        reason = self.blocked("/start-phase 2")   # not committed, not merged
        self.assertIn(texts.phase_files_uncommitted(1, changed), reason)
        self.commit()
        reason = self.blocked("/start-phase 2")
        self.assertIn(texts.previous_not_merged(2, "stage-1"), reason)
        self.assertNotIn("not committed", reason)
        self.switch("main")   # the phase files are not here
        done = texts.done_not_merged(1, "stage-1")
        merge = texts.next_in_new_chat("start-phase", 2, texts.MERGE_FIRST)
        for prompt in ("/summarize-phase", "/summarize-phase 1"):
            text = self.typed(prompt)
            self.assertIn(done, text)
            self.assertTrue(text.endswith(merge), text)
        for args in (["status"], ["status", "1"]):
            self.assertTrue(self.cli(*args).endswith(done + "\n" + merge + "\n"))
        for prompt in ("/start-phase 1", "/start-phase 2", "/start-phase 3", "/start-phase 2 skip: x",
                       "/approve-phase 1", "/build-phase 1", "/build-phase", "/finish-phase 1"):
            text = self.blocked(prompt)
            self.assertIn(done, text)
            self.assertTrue(text.endswith(merge), text)
        self.assertTrue(self.ai_may_write("src/Moth.cs"))
        self.assertEqual(self.git("status", "--porcelain"), "")
        self.git("merge", "-q", "--ff-only", "stage-1")
        self.touch_code()
        text = self.typed("/start-phase 2")
        self.assertIn(texts.carried_concept("Enemy AI"), text)
        self.assertEqual((self.data(1)["status"], self.data(2)["status"]), ("done", "planning"))
        self.assertIn("Scorecard of phase 1", self.typed("/summarize-phase 1"))

    def test_saves_between_runs_of_three_scripts(self):
        self.built()
        self.save("src/Moth.cs", shell([]))
        self.record(["GameTests.Starts", "GameTests.Ends", "MothTests.Turns", "MothTests.Dies"],
                    ["LampTests.Glows", "KeeperTests.Walks"])
        self.assertIn("<- next: TODO 2.1", self.typed("/summarize-phase 1"))
        self.save("src/Lamp.cs", shell(["2.1"]) + "// a draft\n")   # makes all results old
        text = self.typed("/summarize-phase 1")
        self.assertIn(texts.WHY["old"], text)
        self.assertIn("<- next: TODO 2.1", text)
        self.assertIn("Your turn", text)
        self.save("src/Lamp.cs", shell([]))
        self.record(["LampTests.Glows"])   # the tests of one script only
        text = self.typed("/summarize-phase 1")
        self.assertIn("<- next: TODO 3.1", text)

        self.played()
        self.assertTrue(self.typed("/summarize-phase 1").endswith(texts.next_line("finish-phase", 1)))
        self.save("src/Keeper.cs", shell([]) + "// speed 4\n")
        self.record(OWNER)   # a filtered run: the other tests of the suite are not known to pass
        item = texts.suite_not_run("Unit", ["GameTests.Ends", "GameTests.Starts"])
        for text in (self.typed("/summarize-phase 1"), self.blocked("/finish-phase 1")):
            self.assertIn(item, text)
        self.record(["GameTests.Ends"], ["GameTests.Starts"])
        self.assertIn(texts.suite_failing("Unit", ["GameTests.Starts"]), self.blocked("/finish-phase 1"))
        self.record(["GameTests.Starts"])
        self.assertIn(texts.done_text(1), self.typed("/finish-phase 1"))

    def test_tweaks_after_the_tests_passed(self):
        self.built()
        for name in SHELLS:
            self.save(name, shell([]))
        for name, text in TEST_CODE.items():
            self.save(name, text)
        self.assertIn("Phase 1 - build", self.typed("/summarize-phase 1"))   # the first arrival needs fresh results
        games = ["GameTests.Starts", "GameTests.Ends"]
        self.record(OWNER + games)
        self.save("src/Keeper.cs", shell([]) + "// speed 4\n")
        text = self.typed("/summarize-phase 1")
        self.assertIn("Phase 1 - tune", text)
        self.assertIn(texts.WHY["old"], text)
        self.assertTrue(text.endswith(texts.next_line("summarize-phase", 1)))
        self.assertIn(texts.build_is_over(1, "tune"), self.blocked("/build-phase 1"))
        self.record(["KeeperTests.Walks"])   # a filtered run
        self.assertIn("Phase 1 - tune", self.typed("/summarize-phase 1"))
        self.record(failed=["KeeperTests.Walks"])
        self.assertIn("Phase 1 - build", self.typed("/summarize-phase 1"))
        self.save("src/Keeper.cs", shell(["3.1"]))
        self.assertIn("Phase 1 - build", self.typed("/summarize-phase 1"))
        self.save("src/Keeper.cs", shell([]) + "// speed 5\n")
        self.record(OWNER + games)
        self.assertIn("Phase 1 - tune", self.typed("/summarize-phase 1"))

        self.cli("log", "measure", "target=wins", "value=50")
        self.cli("log", "rating", "concept=ai", "rating=with help")
        self.save("Docs/learning/phase-1.md", FULL_MD.replace("Phase 2", "Phase 1"))
        self.save("src/Keeper.cs", shell([]) + "// speed 6\n")
        text = self.typed("/summarize-phase 1")
        self.assertIn("Phase 1 - wrap-up", text)
        self.assertTrue(text.endswith(texts.next_line("summarize-phase", 1)))
        self.assertIn(texts.suite_old("Unit"), self.blocked("/finish-phase 1"))
        self.record(OWNER + games)
        self.assertTrue(self.typed("/summarize-phase 1").endswith(texts.next_line("finish-phase", 1)))
        self.assertIn(texts.done_text(1), self.typed("/finish-phase 1"))

    def test_a_renamed_and_an_ignored_test(self):
        self.built()
        self.played()
        self.save("src/GameTests.cs", "class GameTests {\n  [Ignore(\"later\")] void Starts() {}\n"
                                      "  void EndsLate() { game.Ends(); }\n}\n")
        self.record(OWNER + ["GameTests.EndsLate"])
        self.assertIn(texts.suite_not_run("Unit", ["GameTests.Starts"]), self.blocked("/finish-phase 1"))
        names = [t.split(".") for t in OWNER + ["GameTests.EndsLate"]]
        path = self.tmp / "results.xml"
        path.write_text("<testsuite>%s<testcase classname='GameTests' name='Starts'><skipped/></testcase></testsuite>"
                        % "".join("<testcase classname='%s' name='%s'/>" % (c, m) for c, m in names))
        os.utime(path, (self.tick(),) * 2)
        self.cli("record-tests", "Unit", str(path))
        self.assertIn(texts.done_text(1), self.typed("/finish-phase 1"))

    def test_a_skipped_phase_leaves_the_next_one_alone(self):
        self.built()
        self.assertIn("was skipped", self.typed("/start-phase 2 skip: too hard"))
        self.plan(2)
        plan = full_plan(2)
        for s, name in zip(plan["scripts"], ("Bat", "Wolf", "Door")):
            s.update(name=name, path="src/%s.cs" % name, tests=["%sTests.Moves" % name])
        helpers.write_json(self.root / "Docs" / "learning" / "phase-2.plan.json", plan)
        self.typed("/approve-phase 2")
        self.typed("/build-phase 2")
        tests = [s["tests"][0] for s in plan["scripts"]]
        for s in plan["scripts"]:
            self.save(s["path"], shell(s["todos"]))
            self.save("src/%sTests.cs" % s["name"], "class %sTests { void Moves() {} }\n" % s["name"])
        self.record(["GameTests.Starts", "GameTests.Ends"], tests)
        self.cli("hand-over", "2")
        self.assertTrue(self.ai_may_write("src/New.cs"))
        for s in plan["scripts"]:
            self.save(s["path"], shell([]))
        self.record(["GameTests.Starts", "GameTests.Ends"] + tests)
        self.cli("log", "measure", "target=wins", "value=50")
        self.cli("log", "rating", "concept=ai", "rating=on my own")
        self.save("Docs/learning/phase-2.md", FULL_MD)
        self.assertIn(texts.done_text(2), self.typed("/finish-phase 2"))


if __name__ == "__main__":
    unittest.main()
