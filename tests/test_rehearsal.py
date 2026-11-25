import contextlib
import io
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import helpers
from helpers import FULL_MD, full_plan, shell, suite_result
import learning
from gl import commands, hooks, markdown, plan, project, rehearsal, scan, scorecard, state, store, texts, version

ROOT = Path(__file__).resolve().parent.parent
DESIGN = (ROOT / "docs" / "design.md").read_text(encoding="utf-8")
LEARNING = Path(".claude") / "learning"
ON, OFF = '{"rehearsal": true}', '{"rehearsal": false}'


def design_checks():
    """The checks the design lists after "The checklist says what to type and expect:"."""
    pattern = r"\*\*The checklist\*\* says what to type and expect: (.*?)\. The script ticks"
    sentence = re.search(pattern, DESIGN).group(1)
    found = []
    for item in sentence.split(";"):
        pieces = [p.strip() for p in re.split(r", and |, ", item.strip())]
        command = re.match(r"`/[a-z-]+` ", pieces[0])
        found += [pieces[0]] + [command.group(0) + p for p in pieces[1:]]
    return found


def outer_files(root):
    """Content of every file of the real project: all but what a rehearsal may write."""
    own = [root / LEARNING / n for n in ("rehearsal", "rehearsal-reports", "local", "config.json")]
    return {str(f): f.read_bytes() for f in root.rglob("*")
            if f.is_file() and not any(f == o or o in f.parents for o in own)}


def make_link(link, target):
    """A junction on Windows, which needs no rights, and a symbolic link elsewhere."""
    if os.name == "nt":
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], check=True, stdout=subprocess.DEVNULL)
    else:
        os.symlink(str(target), str(link), target_is_directory=True)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(os.path.realpath(tempfile.mkdtemp()))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = self.tmp / "game"
        self.fake = self.root / LEARNING / "rehearsal"
        self.saved = 1000
        self.session = "s1"
        helpers.make_project(
            self.root, files={"src/Moth.cs": shell(["1.1", "1.2"]), "src/Other.cs": "class O {}\n"},
            phases={2: {"state": {"status": "build", "turn": "owner", "part": 0, "locked": ["src/Moth.cs"],
                                  "results": {"Unit": suite_result({"MothTests.Turns": "failed"})}},
                        "plan": full_plan(), "md": FULL_MD}})

    def switch(self, text):
        """Save config.json, each time with a later change time."""
        helpers.set_switch(self.root, text)
        self.saved += 10
        os.utime(str(self.root / LEARNING / "config.json"), (self.saved, self.saved))

    def found(self):
        return project.find(self.root)

    def look(self):
        """What every hook does first."""
        found = self.found()
        rehearsal.sync(found)
        return found

    def seen(self):
        return store.read(self.root / LEARNING / "local" / "seen.json")

    def on(self):
        self.switch(ON)
        return self.look()

    def mark(self):
        """Change the fake project, to see whether it is made again."""
        (self.fake / "src" / "Moth.cs").write_text("changed\n", encoding="utf-8")

    def restarted(self):
        return (self.fake / "src" / "Moth.cs").read_text(encoding="utf-8") != "changed\n"

    def ticks(self):
        return set(rehearsal.ticks(self.found()))

    # --- calls ---

    def call(self, event, **data):
        return hooks.handle(event, dict({"cwd": str(self.root), "session_id": self.session}, **data), str(self.root))

    def prompt(self, text):
        """(blocked, text) of a typed command."""
        out = self.call("UserPromptSubmit", prompt=text)
        if out.get("decision") == "block":
            return True, out["reason"]
        return False, out["hookSpecificOutput"]["additionalContext"]

    def edit(self, path, **more):
        return self.call("PreToolUse", tool_name="Edit", tool_use_id="t1", tool_input=dict(
            {"file_path": str(path), "old_string": "class", "new_string": "struct"}, **more))

    def cli(self, *args):
        out = io.StringIO()
        with mock.patch.object(os, "getcwd", return_value=str(self.root)), contextlib.redirect_stdout(out):
            code = learning.main(list(args))
        return code, out.getvalue()


class TemplateTests(Base):
    def test_template_state_is_2_of_5(self):
        active = self.on().active
        st = state.compute(active, 2)
        self.assertEqual((st.todos_done, st.todos_total), (2, 5))
        self.assertEqual((st.status, st.turn, st.part, st.parts_total, st.next_todo), ("build", "owner", 0, 2, "1.3"))
        self.assertEqual((st.problems, st.wrong_branch, st.plan_changed, st.lost_todos), ([], None, False, []))
        self.assertEqual((st.targets_met, st.targets_total), (0, 3))
        self.assertEqual([(s.name, s.status, s.tests_passed, s.tests_total) for s in st.scripts],
                         [("Moth", "in progress", 2, 3), ("Lantern", "not started", 0, 2)])
        self.assertEqual(len(store.read(active.plan_path(2))["concepts"]), 2)

    def test_phases_are_as_the_script_leaves_them(self):
        active = self.on().active
        self.assertEqual((plan.plan_gaps(active, 1), plan.plan_gaps(active, 2)), ([], []))
        one = store.read(active.state_path(1))
        self.assertEqual((one["status"], one["closing"]["pending"], one["locked"]), ("done", False, []))
        for n in (1, 2):
            self.assertFalse(state.plan_differs(active, n, store.read(active.state_path(n))))
        self.assertTrue(state.is_merged(active, "stage-1"))
        self.assertFalse(state.is_merged(active, "stage-2"))
        weak, differently = state.carry_over(active, 1)
        self.assertEqual(store.read(active.state_path(2))["carried"],
                         [texts.carried_concept(w) for w in weak] + [texts.carried_differently(differently)])
        self.assertIn(scorecard.render(active, 1).split("\n", 1)[1], active.md_path(1).read_text(encoding="utf-8"))
        self.assertTrue(markdown.load(active.md_path(1)).has_section("scorecard"))

    def test_the_template_is_plain_and_complete(self):
        template = ROOT / "rehearsal" / "project"
        self.assertTrue((template / LEARNING / "project.json").is_file())
        files = [f for f in (ROOT / "rehearsal").rglob("*") if f.is_file()]
        for f in files:
            self.assertNotIn(b"\r", f.read_bytes().replace(b"\r\n", b"\n"), f)
            f.read_bytes().decode("utf-8")
        ignored = subprocess.run(["git", "check-ignore"] + [str(f) for f in files], cwd=str(ROOT),
                                 stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.assertEqual(ignored.stdout, b"")


class RestartTests(Base):
    def test_off_changes_nothing(self):
        before = {str(f) for f in self.root.rglob("*")}
        self.switch(OFF)
        self.look()
        self.assertEqual({str(f) for f in self.root.rglob("*")}, before | {str(self.root / LEARNING / "config.json")})

    def test_off_to_on_restarts(self):
        self.switch(OFF)
        self.look()
        self.assertFalse(self.fake.exists())
        self.on()
        self.assertEqual(self.seen()["run"], 1)
        self.mark()
        self.switch(OFF)
        self.look()
        self.assertFalse(self.restarted(), "off leaves it alone")
        self.on()
        self.assertTrue(self.restarted())
        self.assertEqual(self.seen()["run"], 2)

    def test_off_on_between_two_looks_restarts(self):
        self.on()
        self.mark()
        self.switch(OFF)
        self.switch(ON)
        self.look()
        self.assertTrue(self.restarted())

    def test_saving_again_while_on_restarts(self):
        self.on()
        self.mark()
        self.switch(ON)
        self.look()
        self.assertTrue(self.restarted())
        self.assertEqual(self.seen()["run"], 2)

    def test_on_unchanged_does_not_restart(self):
        self.on()
        self.mark()
        before = (self.root / LEARNING / "local" / "seen.json").stat().st_mtime_ns
        for _ in range(3):
            self.look()
        self.assertFalse(self.restarted())
        self.assertEqual(self.seen()["run"], 1)
        self.assertEqual((self.root / LEARNING / "local" / "seen.json").stat().st_mtime_ns, before)

    def test_the_change_time_is_kept_exactly(self):
        self.switch(ON)
        path = self.root / LEARNING / "config.json"
        os.utime(str(path), ns=(1234567890123456700, 1234567890123456700))
        self.look()
        self.assertEqual(self.seen()["mtime"], path.stat().st_mtime_ns)
        self.mark()
        os.utime(str(path), ns=(1234567890123456800, 1234567890123456800))
        self.look()
        self.assertTrue(self.restarted())

    def test_a_folder_that_vanished_is_made_again(self):
        self.on()
        shutil.rmtree(str(self.fake))
        found = self.look()
        self.assertEqual(state.compute(found.active, 2).todos_done, 2)
        self.assertEqual(self.seen()["run"], 2)
        (self.fake / LEARNING / "project.json").unlink()
        self.assertIn("run 3", self.call("SessionStart")["systemMessage"])

    def test_every_hook_and_status_look_first(self):
        for event in hooks.EVENTS:
            self.switch(ON)
            self.call(event, tool_name="Bash", tool_input={}, tool_use_id="t", prompt="x", last_assistant_message="")
        self.assertEqual(self.seen()["run"], len(hooks.EVENTS))
        self.switch(ON)
        self.assertEqual(self.cli("status")[0], 0)
        self.assertEqual(self.seen()["run"], len(hooks.EVENTS) + 1)

    def test_session_start_shows_the_new_run(self):
        self.on()
        self.switch(ON)
        out = self.call("SessionStart")
        self.assertIn("(REHEARSAL run 2, ", out["systemMessage"])
        self.assertNotIn("\n", out["systemMessage"])
        self.assertIn("rehearse", out["hookSpecificOutput"]["additionalContext"])

    def test_results_are_newer_than_the_code(self):
        active = self.on().active
        for n in (1, 2):
            self.assertGreaterEqual(store.read(active.state_path(n))["results"]["Unit"]["time"],
                                    scan.last_code_change(active))

    def test_old_files_are_gone_after_a_restart(self):
        self.on()
        (self.fake / "src" / "More.cs").write_text("x", encoding="utf-8")
        deep = self.fake / "a" / "b"
        deep.mkdir(parents=True)
        (deep / "c.txt").write_text("x", encoding="utf-8")
        os.chmod(str(deep / "c.txt"), 0o444)
        self.on()
        self.assertFalse((self.fake / "src" / "More.cs").exists())
        self.assertFalse((deep / "c.txt").exists())

    def test_two_at_once_restart_once(self):
        self.switch(ON)
        errors = []

        def work():
            try:
                self.look()
                self.assertEqual(state.compute(self.found().active, 2).todos_done, 2)
            except BaseException as e:
                errors.append(e)

        threads = [threading.Thread(target=work) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(self.seen()["run"], 1)

    def test_odd_seen_file_starts_again(self):
        self.on()
        for text in ("{broken", "[]", '{"mtime": "x", "run": "y"}', '{"mtime": true, "run": -1}'):
            (self.root / LEARNING / "local" / "seen.json").write_text(text, encoding="utf-8")
            self.mark()
            self.look()
            self.assertTrue(self.restarted(), text)

    def test_a_broken_seen_file_is_not_deleted_outside_the_lock(self):
        self.on()
        path = self.root / LEARNING / "local" / "seen.json"
        path.write_text("{broken", encoding="utf-8")
        self.assertEqual(rehearsal._seen(self.found()), {})
        self.assertEqual(path.read_text(encoding="utf-8"), "{broken")
        errors = []

        def work():
            try:
                self.look()
            except BaseException as e:
                errors.append(e)

        threads = [threading.Thread(target=work) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual((errors, self.seen()["run"]), ([], 2))

    def test_a_file_that_vanished_meanwhile_counts_as_removed(self):
        for name in ("unlink", "lstat"):
            self.on()
            real, gone = getattr(os, name), []

            def vanish(path, *args, **more):
                if os.fspath(path).endswith("Keeper.cs") and not gone:
                    gone.append(path)
                    os.remove(path)
                return real(path, *args, **more)

            self.switch(ON)
            with mock.patch.object(os, name, side_effect=vanish):
                self.look()
            self.assertEqual(len(gone), 1, name)
            self.assertTrue((self.fake / "src" / "Keeper.cs").is_file())

    def test_run_numbers_go_on_when_local_was_deleted(self):
        self.on()
        rehearsal.tick(self.found(), "ask-todo", "owner")
        old = rehearsal.report_path(self.found(), 1).read_bytes()
        shutil.rmtree(str(self.root / LEARNING / "local"))
        self.look()
        self.assertEqual(self.seen()["run"], 2)
        self.assertEqual(rehearsal.report_path(self.found(), 1).read_bytes(), old)

    def test_a_rehearsal_project_itself_is_never_synced(self):
        active = self.on().active
        active.rehearsal = True
        helpers.set_switch(self.fake, ON)
        rehearsal.sync(active)
        self.assertFalse((self.fake / LEARNING / "rehearsal").exists())


class SafetyTests(Base):
    """Only <root>/.claude/learning/rehearsal is ever emptied."""

    def valuable(self):
        folder = self.tmp / "valuable"
        (folder / "sub").mkdir(parents=True)
        (folder / "a.txt").write_text("precious", encoding="utf-8")
        (folder / "sub" / "b.txt").write_text("precious", encoding="utf-8")
        return folder

    def intact(self, folder):
        self.assertEqual({f.name for f in folder.rglob("*") if f.is_file()}, {"a.txt", "b.txt"})

    def refused(self):
        before = outer_files(self.root)
        with self.assertRaises(rehearsal.RehearsalError) as caught:
            self.look()
        self.assertFalse((self.root / LEARNING / "local" / "seen.json").exists())
        self.assertEqual(outer_files(self.root), before)
        return str(caught.exception)

    def test_a_link_is_refused_and_left(self):
        folder = self.valuable()
        make_link(self.fake, folder)
        self.switch(ON)
        self.assertIn("rehearsal", self.refused())
        self.intact(folder)
        answer = self.call("PreToolUse", tool_name="Bash", tool_input={}, tool_use_id="t")["hookSpecificOutput"]
        self.assertEqual(answer["permissionDecision"], "deny")
        self.assertTrue(answer["permissionDecisionReason"].startswith("guided-learning error: "))
        self.assertTrue(self.prompt("hello")[0])
        self.assertEqual(list(self.call("SessionStart")), ["systemMessage"])
        self.intact(folder)
        self.switch(OFF)
        self.assertIsNone(self.call("PreToolUse", tool_name="Bash", tool_input={}, tool_use_id="t"))

    def test_a_link_above_it_is_refused(self):
        outside = self.valuable()
        target = outside / "learning"
        shutil.move(str(self.root / LEARNING), str(target))
        (target / "rehearsal").mkdir()
        (target / "rehearsal" / "mine.txt").write_text("precious", encoding="utf-8")
        make_link(self.root / LEARNING, target)
        self.switch(ON)
        self.refused()
        self.assertTrue((target / "rehearsal" / "mine.txt").is_file())

    def test_a_link_put_there_later_is_refused(self):
        self.on()
        moved = self.tmp / "moved"
        shutil.move(str(self.fake), str(moved))
        make_link(self.fake, moved)
        (moved / "mine.txt").write_text("precious", encoding="utf-8")
        with self.assertRaises(rehearsal.RehearsalError):
            self.look()
        self.assertEqual(self.seen()["run"], 1)
        self.assertTrue((moved / "mine.txt").is_file())

    def test_a_link_that_leads_nowhere_is_refused(self):
        folder = self.valuable()
        make_link(self.fake, folder)
        shutil.rmtree(str(folder))
        self.switch(ON)
        self.refused()

    def test_a_file_is_refused_and_left(self):
        self.fake.write_text("mine", encoding="utf-8")
        self.switch(ON)
        self.refused()
        self.assertEqual(self.fake.read_text(encoding="utf-8"), "mine")

    def test_a_link_inside_is_removed_and_not_followed(self):
        self.on()
        folder = self.valuable()
        make_link(self.fake / "linked", folder)
        make_link(self.fake / "src" / "linked", self.root / "src")
        self.on()
        self.assertFalse(os.path.lexists(str(self.fake / "linked")))
        self.assertFalse(os.path.lexists(str(self.fake / "src" / "linked")))
        self.intact(folder)
        self.assertTrue((self.root / "src" / "Moth.cs").is_file())

    def test_real_folders_inside_are_refused(self):
        kept = self.fake / "src" / "Real.cs"
        for settings in ({"code": [".claude/learning/rehearsal/src"]}, {"code": [".claude/learning/rehearsal"]},
                         {"docs": ".claude/learning/rehearsal/Docs"}):
            kept.parent.mkdir(parents=True, exist_ok=True)
            kept.write_text("real", encoding="utf-8")
            helpers.write_json(self.root / LEARNING / "project.json", dict(helpers.PROJECT_JSON, **settings))
            self.switch(ON)
            if "docs" in settings:
                with self.assertRaises(project.BadSettings):   # such a setting is refused before that
                    self.look()
            else:
                self.refused()
            self.assertEqual(kept.read_text(encoding="utf-8"), "real")

    def test_real_code_linked_into_it_is_refused(self):
        shutil.rmtree(str(self.root / "src"))
        (self.fake / "code").mkdir(parents=True)
        (self.fake / "code" / "Real.cs").write_text("real", encoding="utf-8")
        make_link(self.root / "src", self.fake / "code")
        self.switch(ON)
        self.refused()
        self.assertTrue((self.fake / "code" / "Real.cs").is_file())

    def test_a_restart_that_fails_is_not_noted(self):
        self.on()
        before = self.seen()
        self.switch(ON)
        with mock.patch.object(store, "write_text", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.look()
        self.assertEqual(self.seen(), before)
        self.look()
        self.assertEqual(self.seen()["run"], 2)
        self.assertEqual(state.compute(self.found().active, 2).todos_done, 2)

    def test_a_missing_template_leaves_the_old_folder(self):
        self.on()
        self.mark()
        self.switch(ON)
        with mock.patch.object(rehearsal, "TEMPLATE", self.tmp / "nothing"):
            with self.assertRaises(rehearsal.RehearsalError):
                self.look()
        self.assertFalse(self.restarted())
        self.assertEqual(self.seen()["run"], 1)

    def test_code_folder_of_the_whole_game_leaves_out_the_rehearsal(self):
        """The setting "." is allowed, so the fake code lies below a real code folder."""
        helpers.write_json(self.root / LEARNING / "project.json", dict(helpers.PROJECT_JSON, code=["."]))
        found = self.found()
        marked = ["MothTests.Rests"]
        before = (scan.todos_in_code(found), scan.owner_marks(found, marked), scan.last_code_change(found))
        self.on()
        self.assertEqual((scan.todos_in_code(found), scan.owner_marks(found, marked), scan.last_code_change(found)), before)
        self.assertTrue(scan.owner_marks(self.found().active, marked))
        store.write(found.state_path(2), {"status": "planning"})
        self.assertIsNone(self.edit(self.fake / "src" / "Other.cs"))
        self.assertIsNotNone(self.edit(self.root / "src" / "Other.cs"))


class SimulationTests(Base):
    def setUp(self):
        super().setUp()
        self.on()

    def active(self):
        return self.found().active

    def compute(self, n=2):
        return state.compute(self.active(), n)

    def cut(self, rel, text):
        path = self.fake / rel
        lines = path.read_text(encoding="utf-8").split("\n")
        path.write_bytes("\n".join(x for x in lines if text not in x).encode("utf-8"))

    def test_only_while_the_switch_is_on(self):
        self.switch(OFF)
        for args in (("pass",), ("fail",), ("merge",), ("branch",), ("report",), ("check", "ask-todo")):
            code, out = self.cli("rehearse", *args)
            self.assertEqual((code, out), (1, texts.REHEARSE_OFF + "\n"), args)

    def test_wrong_words_are_refused(self):
        for args in ((), ("jump",), ("pass", "x"), ("branch", "a", "b"), ("check",), ("check", "nonsense"),
                     ("check", "finish-early")):
            code, out = self.cli("rehearse", *args)
            self.assertEqual(code, 1, args)
            self.assertNotIn("Error", out)

    def test_fail_after_a_removed_todo(self):
        self.cut("src/Moth.cs", "TODO(owner 1.3)")
        self.assertEqual(self.compute().scripts[0].status, "unknown")
        self.assertEqual(self.cli("rehearse", "fail")[0], 0)
        moth = self.compute().scripts[0]
        self.assertEqual((moth.status, moth.todos_left), ("in progress", []))
        self.assertEqual(moth.failing, ["MothTests.Turns", "MothTests.Chases", "MothTests.Rests"])
        self.assertEqual(self.cli("rehearse", "pass")[0], 0)
        st = self.compute()
        self.assertEqual((st.scripts[0].status, st.turn, st.part), ("done", "ai", 1))

    def test_fail_keeps_a_done_script(self):
        self.cut("src/Moth.cs", "TODO(owner 1.3)")
        self.cli("rehearse", "pass")
        self.cut("src/Lantern.cs", "nothing at all")   # a save makes the results old
        os.utime(str(self.fake / "src" / "Lantern.cs"), (time.time() + 60, time.time() + 60))
        self.assertEqual(self.compute().scripts[0].status, "unknown")
        self.cli("rehearse", "fail")
        self.assertEqual(self.compute().scripts[0].status, "done")
        tests = store.read(self.active().state_path(2))["results"]["Unit"]["tests"]
        self.assertEqual(tests, {"KeeperTests.Walks": "passed", "MothTests.Turns": "passed",
                                 "MothTests.Chases": "passed", "MothTests.Rests": "passed",
                                 "LanternTests.Burns": "failed", "LanternTests.Shines": "failed"})

    def test_pass_notes_that_the_tuning_is_reached(self):
        self.cut("src/Moth.cs", "TODO(owner")
        self.cli("rehearse", "pass")   # part 2 is not handed over yet
        self.assertNotIn("reached", store.read(self.active().state_path(2)))
        self.active().update_state(2, lambda d: d.update(part=1, turn="owner"))
        self.cut("src/Lantern.cs", "TODO(owner")
        self.cli("rehearse", "pass")
        self.assertEqual(store.read(self.active().state_path(2))["reached"], "tune")
        for name in ("Moth", "Lantern"):   # an edit while tuning
            os.utime(str(self.fake / "src" / (name + ".cs")), (time.time() + 60,) * 2)
        st = self.compute()
        self.assertEqual((st.status, st.scripts[0].status), ("tune", "unknown"))
        moth = self.fake / "src" / "Moth.cs"
        text = moth.read_bytes()
        moth.write_bytes(text + b"// TODO(owner 1.3) once more\n")
        self.cli("rehearse", "fail")
        self.assertNotIn("reached", store.read(self.active().state_path(2)))
        moth.write_bytes(text)
        os.utime(str(moth), (time.time() + 120,) * 2)   # saved: the failure is old
        self.assertEqual(self.compute().status, "build")
        self.cli("rehearse", "pass")
        self.assertEqual(store.read(self.active().state_path(2))["reached"], "tune")

    def test_results_need_a_phase_in_build(self):
        self.active().update_state(2, lambda d: d.update(status="done"))
        self.assertEqual(self.cli("rehearse", "pass")[0], 1)

    def test_branch(self):
        self.assertIsNone(self.compute().wrong_branch)
        code, out = self.cli("rehearse", "branch")
        self.assertEqual((code, self.compute().wrong_branch), (0, "main"))
        shown = self.cli("status", "2")[1]
        self.assertIn("rehearse branch stage-2", shown)
        self.assertNotIn("git switch", shown)
        self.cli("rehearse", "branch", "stage-2")
        self.assertIsNone(self.compute().wrong_branch)

    def test_merge(self):
        self.assertEqual(self.cli("rehearse", "merge")[0], 0)
        self.assertTrue(state.is_merged(self.active(), "stage-2"))
        self.cli("rehearse", "branch", "x")
        self.assertTrue(state.is_merged(self.active(), "stage-1"))

    def test_merge_without_a_branch_is_refused(self):
        for n in (1, 2):
            self.active().update_state(n, lambda d: d.update(branch=None))
        self.assertEqual(self.cli("rehearse", "merge")[0], 1)

    def test_without_sim_json_the_own_branch_and_nothing_merged(self):
        path = self.fake / LEARNING / "local" / "sim.json"
        for text in (None, "{broken", '{"branch": 5, "merged": "x"}'):
            path.unlink() if text is None else path.write_text(text, encoding="utf-8")
            self.assertEqual(state.current_branch(self.active()), "stage-2")
            self.assertFalse(state.is_merged(self.active(), "stage-1"))

    def test_git_is_never_asked_for_the_fake_project(self):
        with mock.patch.object(state, "_git", side_effect=AssertionError):
            self.compute()
            state.is_merged(self.active(), "stage-2")

    def test_a_real_project_is_never_simulated(self):
        helpers.write_json(self.root / LEARNING / "local" / "sim.json", {"branch": "x", "merged": ["y"]})
        with mock.patch.object(state, "_git", return_value=None) as git:
            self.assertIsNone(state.current_branch(self.found()))
            state.is_merged(self.found(), "y")
        self.assertTrue(git.called)

    def test_tuning_leaves_the_code_alone_or_needs_new_results(self):
        line = next(c for c in rehearsal.checklist() if c.id == "finish")
        self.assertIn("without editing the code", line.type)
        self.assertIn("`rehearse pass` again", line.type)

    def test_start_phase_stops_at_planning(self):
        self.active().update_state(2, lambda d: d.update(status="done", locked=[]))
        self.cli("rehearse", "merge")
        for _ in range(2):   # again, in a new chat
            blocked, text = self.prompt("/start-phase 3")
            self.assertFalse(blocked, text)
            self.assertIn("Planning would start here", text)
            self.assertNotIn("Plan it with the owner", text)
            self.assertTrue(text.endswith(texts.next_line("approve-phase", 3)))
        self.assertEqual(store.read(self.active().state_path(3))["status"], "planning")
        self.assertTrue(self.active().plan_path(3).is_file())
        self.assertTrue(self.active().md_path(3).is_file())
        self.assertFalse((self.root / "Docs" / "learning" / "phase-3.json").exists())
        skill = (ROOT / "skills" / "start-phase" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("Planning would start here", skill)

    def test_the_text_names_the_folder_and_the_simulation(self):
        text = self.prompt("/summarize-phase 2")[1]
        self.assertTrue(text.startswith("REHEARSAL run 1"))
        self.assertIn(".claude/learning/rehearsal", text)
        self.assertIn("run.sh\" rehearse", text)
        self.assertIn("2 of 5 TODOs done", text)
        self.assertTrue(text.endswith(texts.next_line("summarize-phase", 2)))
        blocked = self.prompt("/finish-phase 2")[1]
        self.assertTrue(blocked.startswith("REHEARSAL run 1"))
        self.switch(OFF)
        self.assertNotIn("REHEARSAL", self.prompt("/summarize-phase 2")[1])

    def test_a_restart_during_a_tool_call_reports_only_the_switch(self):
        self.mark()
        self.call("PreToolUse", tool_name="Bash", tool_input={}, tool_use_id="t")
        self.switch(ON)
        helpers.set_switch(self.root, ON + "\n")
        out = self.call("PostToolUse", tool_name="Bash", tool_input={}, tool_use_id="t")
        self.assertEqual(out["systemMessage"], texts.files_changed_owner([".claude/learning/config.json"]))

    def test_reports_are_guarded(self):
        path = self.root / LEARNING / "rehearsal-reports" / "run-1.md"
        self.assertEqual(self.edit(path)["hookSpecificOutput"]["permissionDecision"], "deny")


class ReportTests(Base):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(version, "plugin_hash", return_value="aaaaaa")
        self.hash = patcher.start()
        self.addCleanup(patcher.stop)
        self.on()

    def test_run_number_and_report_kept(self):
        self.assertTrue(rehearsal.tick(self.found(), "finish-early"))
        self.assertFalse(rehearsal.tick(self.found(), "finish-early"), "the first time counts")
        self.on()
        self.assertEqual(self.seen()["run"], 2)
        self.assertEqual(self.ticks(), set())
        kept = (self.root / LEARNING / "rehearsal-reports" / "run-1.md").read_text(encoding="utf-8")
        self.assertIn("run 1", kept)
        self.assertIn("[x] finish-early", kept)
        self.assertIn("[ ] finish ", kept)
        rehearsal.tick(self.found(), "start-early")
        self.on()
        self.assertEqual((self.root / LEARNING / "rehearsal-reports" / "run-1.md").read_text(encoding="utf-8"), kept)
        self.assertIn("[x] start-early", (self.root / LEARNING / "rehearsal-reports" / "run-2.md").read_text(
            encoding="utf-8"))
        self.assertEqual(self.seen()["run"], 3)

    def test_a_kept_report_is_not_written_again(self):
        rehearsal.tick(self.found(), "finish-early")
        path = rehearsal.report_path(self.found(), 1)
        kept = path.read_bytes()
        (self.root / LEARNING / "local" / "rehearsal-runs" / "run-1.json").write_text("{broken", encoding="utf-8")
        self.on()
        self.assertEqual(path.read_bytes(), kept)
        rehearsal.tick(self.found(), "start-early")
        path = rehearsal.report_path(self.found(), 2)
        kept = path.read_bytes()
        other = self.tmp / "checklist.md"
        other.write_text("| `new-check` | - | a | b | owner |\n", encoding="utf-8")
        with mock.patch.object(rehearsal, "CHECKLIST", other):
            self.on()
        self.assertEqual(path.read_bytes(), kept)
        self.on()   # run 3 had no tick, so its report comes at the restart
        self.assertIn("run 3", rehearsal.report_path(self.found(), 3).read_text(encoding="utf-8"))

    def test_resumed_means_the_same_state(self):
        self.prompt("/summarize-phase 2")
        path = self.fake / "src" / "Moth.cs"
        shown = path.read_bytes()
        path.write_bytes(shown.replace(b"TODO(owner 1.3)", b"done"))
        self.session = "s2"
        self.prompt("/summarize-phase 2")
        self.assertNotIn("resume-closed", self.ticks())
        path.write_bytes(shown)
        self.prompt("/summarize-phase 2")
        self.assertIn("resume-closed", self.ticks())

    def test_report_says_who_and_which_plugin(self):
        rehearsal.tick(self.found(), "finish-early")
        self.assertEqual(self.cli("rehearse", "check", "ask-todo")[0], 0)
        text = rehearsal.report(self.found())
        for part in ("run 1", "%s aaaaaa" % version.VERSION, "[x] finish-early", "script", "[x] ask-todo", "owner",
                     "[ ] resume-half", "2 of %d" % len(rehearsal.checklist())):
            self.assertIn(part, text)
        code, out = self.cli("rehearse", "report")
        self.assertEqual(code, 0)
        self.assertIn(text.strip(), out)
        self.assertIn(rehearsal.compare(self.found()), out)

    def test_unknown_check_is_an_error(self):
        with self.assertRaises(rehearsal.RehearsalError):
            rehearsal.tick(self.found(), "nonsense")

    def test_compare_names_the_difference(self):
        self.assertIn("no earlier run", rehearsal.compare(self.found()))
        rehearsal.tick(self.found(), "finish-early")
        rehearsal.tick(self.found(), "start-early")
        self.hash.return_value = "bbbbbb"
        self.on()
        rehearsal.tick(self.found(), "start-early")
        rehearsal.tick(self.found(), "wrong-branch")
        text = rehearsal.compare(self.found())
        self.assertIn("run 1", text)
        self.assertEqual(re.findall(r"finish-early|start-early|wrong-branch", text), ["wrong-branch", "finish-early"])
        for part in ("aaaaaa", "bbbbbb"):
            self.assertIn(part, text)
        shown = self.prompt("/summarize-phase 2")[1]   # it ticks resume-half
        self.assertIn(rehearsal.compare(self.found()), shown)
        self.assertIn(rehearsal.compare(self.found()), self.cli("status")[1])

    def test_compare_of_two_equal_runs(self):
        rehearsal.tick(self.found(), "finish-early")
        self.on()
        rehearsal.tick(self.found(), "finish-early")
        self.assertNotIn("finish-early", rehearsal.compare(self.found()))
        self.assertIn("the same", rehearsal.compare(self.found()))

    def test_a_tick_that_fails_never_blocks(self):
        for target in ("tick", "compare"):
            with mock.patch.object(rehearsal, target, side_effect=OSError("disk full")):
                blocked, text = self.prompt("/summarize-phase 2")
                self.assertFalse(blocked)
                self.assertIn("2 of 5 TODOs done", text)
                self.assertIn("disk full", text)
        with mock.patch.object(rehearsal, "tick", side_effect=OSError("disk full")):
            self.assertIn("owner's turn", self.prompt("/build-phase 2")[1])
            denied = self.edit(self.fake / "src" / "Moth.cs")["hookSpecificOutput"]
            self.assertIn("is locked", denied["permissionDecisionReason"])
            self.assertIn("disk full", denied["permissionDecisionReason"])

    def test_the_status_of_the_command_line_ticks_nothing(self):
        self.cli("status")
        self.assertEqual(self.ticks(), set())

    def test_an_edit_of_the_real_project_ticks_nothing(self):
        self.assertIsNotNone(self.edit(self.root / "src" / "Moth.cs"))
        self.assertEqual(self.ticks(), set())

    def test_a_new_chat_is_another_session(self):
        self.prompt("/summarize-phase 2")
        self.prompt("/summarize-phase 2")
        self.assertEqual(self.ticks(), {"resume-half"})
        self.session = None
        self.prompt("/summarize-phase 2")
        self.assertEqual(self.ticks(), {"resume-half"})
        self.session = "s2"
        self.prompt("/summarize-phase 2")
        self.assertEqual(self.ticks(), {"resume-half", "resume-closed"})


class ChecklistTests(unittest.TestCase):
    def test_every_design_check_is_in_the_checklist(self):
        wanted = design_checks()
        self.assertEqual(len(wanted), 15)
        self.assertIn("`/start-phase` with a skip", wanted)
        covered = {c.covers for c in rehearsal.checklist()}
        for check in wanted:
            self.assertIn(check, covered)
        self.assertEqual(covered - set(wanted), {"-"})

    def test_every_line_is_complete(self):
        lines = rehearsal.checklist()
        self.assertEqual(len({c.id for c in lines}), len(lines))
        for c in lines:
            self.assertRegex(c.id, r"^[a-z][a-z-]+$")
            self.assertIn(c.by, ("script", "owner"))
            self.assertTrue(c.type and c.expect, c.id)

    def test_the_build_stops_by_itself_for_a_question(self):
        """Closing the chat in the middle must not depend on how fast the owner is."""
        self.assertNotIn("Esc", (ROOT / "rehearsal" / "checklist.md").read_text(encoding="utf-8"))
        docs = ROOT / "rehearsal" / "project" / "Docs" / "learning"
        tasks = store.read(docs / "phase-2.plan.json")["parts"][1]["tasks"]
        self.assertEqual(len(tasks), 2)
        self.assertRegex(tasks[1], "^Ask the owner .* wait for the answer$")

    def test_the_commands_in_it_exist(self):
        text = (ROOT / "rehearsal" / "checklist.md").read_text(encoding="utf-8")
        for command in re.findall(r"`/([a-z-]+)", text):
            self.assertIn(command, texts.COMMANDS)
        for word in re.findall(r"`rehearse ([a-z]+)", text):
            self.assertIn(word, rehearsal.WORDS)

    def test_nobody_and_no_real_path_is_named(self):
        for f in (ROOT / "rehearsal").rglob("*"):
            if f.is_file():
                self.assertNotRegex(f.read_text(encoding="utf-8"), r"@|[A-Z]:\\")


class FullRunTests(Base):
    """The checklist from top to bottom, as the owner and the AI would do it."""

    cut = SimulationTests.cut

    def blocked(self, text, *parts):
        blocked, shown = self.prompt(text)
        self.assertTrue(blocked, shown)
        for part in parts:
            self.assertIn(part, shown)

    def accepted(self, text, *parts):
        blocked, shown = self.prompt(text)
        self.assertFalse(blocked, shown)
        for part in parts:
            self.assertIn(part, shown)
        return shown

    def run_cli(self, *args):
        code, out = self.cli(*args)
        self.assertEqual(code, 0, out)
        return out

    def run_it(self):
        self.on()
        self.call("SessionStart")
        self.accepted("/summarize-phase 2", "2 of 5 TODOs done", "next: TODO 1.3")
        self.session = "s2"
        self.accepted("/summarize-phase 2")
        self.assertIsNotNone(self.edit(self.fake / "src" / "Moth.cs"))
        self.blocked("/build-phase 2", "owner's turn")
        self.blocked("/finish-phase 2", "cannot be closed")
        self.blocked("/start-phase 3", "not finished")
        self.run_cli("rehearse", "branch")
        self.accepted("/summarize-phase 2", "main")
        self.run_cli("rehearse", "branch", "stage-2")
        self.cut("src/Moth.cs", "TODO(owner 1.3)")
        self.run_cli("rehearse", "fail")
        self.accepted("/summarize-phase 2", "in progress", "failing: MothTests.Turns")
        self.cut("src/Tests/MothTests.cs", "[Explicit")
        self.run_cli("rehearse", "pass")
        self.accepted("/build-phase 2", "part 2 of 2", "1. [open]")
        self.run_cli("log", "task", "part=2", "index=1", "phase=2")
        self.session = "s3"
        self.accepted("/build-phase 2", "1. [done]", "2. [open] Ask the owner")
        lantern = (self.fake / "src" / "Lantern.cs").read_bytes()
        self.cut("src/Lantern.cs", "TODO(owner 2.2)")
        self.run_cli("rehearse", "fail")
        self.run_cli("log", "task", "part=2", "index=2", "phase=2")   # the owner answered
        code, out = self.cli("hand-over", "2")
        self.assertEqual((code, out.count("  - ")), (1, 1), out)   # nothing but the TODO is missing
        self.assertIn("TODO(owner 2.2)", out)
        (self.fake / "src" / "Lantern.cs").write_bytes(lantern)
        self.run_cli("rehearse", "fail")
        self.assertIn("part 2 handed over. Your turn: 1 script, 2 TODOs.", self.run_cli("hand-over", "2"))
        self.finish()
        self.blocked("/start-phase 3", "not merged")
        self.run_cli("rehearse", "merge")
        self.session = "s5"
        self.accepted("/start-phase 3", "Planning would start here")
        self.blocked("/build-phase 3", "not approved")
        self.assertIn("still being planned", self.edit(self.fake / "src" / "Lantern.cs")[
            "hookSpecificOutput"]["permissionDecisionReason"])
        shown = self.accepted("/start-phase 4 skip: trying it out", texts.skipped_text(3, "trying it out"),
                              "Phase 4: ", "Planning would start here", texts.CARRIED_HEADING,
                              texts.bullet(texts.plan_not_approved(3)))
        self.assertNotIn("run.sh", shown)

    def finish(self):
        self.cut("src/Lantern.cs", "TODO(owner")
        self.cut("src/Tests/LanternTests.cs", "[Explicit")
        self.run_cli("rehearse", "pass")
        self.session = "s4"
        self.accepted("/summarize-phase 2", "Phase 2 - tune", "Target nights")
        for target, value in (("nights", 4), ("oil", 20), ("escapes", 30)):
            self.run_cli("log", "measure", "target=" + target, "value=%d" % value, "phase=2")
        active = self.found().active
        text = active.md_path(2).read_text(encoding="utf-8")
        text = text.replace("## Concept summary\n", "### q1\nnearest\n\n### q2\nless far away\n\n## Concept summary\n\n"
                            "### Enemy AI\nstates\n\n### Light and resources\nfalloff\n")
        text = text.replace("## Lessons\n", "## Lessons\n- a\n- b\n- c\n")
        text = text.replace("Surprised me:", "Surprised me: oil").replace("Differently:", "Differently: plan")
        store.write_text(active.md_path(2), text)
        for concept in ("ai", "light"):
            self.run_cli("log", "rating", "concept=" + concept, "rating=with help", "phase=2")
        shown = self.accepted("/finish-phase 2")
        closing = commands.closing_text(active, 2)
        self.assertEqual(shown, texts.rehearsal_short(rehearsal.render.run_number(self.found())) + "\n" + closing)
        self.assertEqual(self.call("Stop", last_assistant_message="no")["decision"], "block")
        self.assertIsNone(self.call("Stop", last_assistant_message="Done.\n" + closing))

    def test_nothing_outside_rehearsal_changes(self):
        before = outer_files(self.root)
        self.assertIn(str(self.root / "Docs" / "learning" / "phase-2.json"), before)
        self.run_it()
        self.run_cli("rehearse", "check", "ask-todo")
        self.run_cli("rehearse", "report")
        self.on()
        self.run_it()
        self.switch(OFF)
        self.look()
        self.assertEqual(outer_files(self.root), before)

    def test_the_script_ticks_every_line_of_its_own(self):
        self.run_it()
        self.assertEqual(self.ticks(), {c.id for c in rehearsal.checklist() if c.by == "script"})

    def test_two_runs_compare_as_the_same(self):
        self.run_it()
        self.run_it()
        self.assertIn("the same", rehearsal.compare(self.found()))
        self.assertIn("run 2", self.call("SessionStart")["systemMessage"])

    def test_nothing_is_ticked_before_it_happens(self):
        self.on()
        self.accepted("/summarize-phase 1")
        self.blocked("/start-phase 3 skip:")
        self.blocked("/start-phase 2")
        self.blocked("/build-phase 9")
        self.blocked("/approve-phase x")
        self.cli("hand-over")
        self.assertEqual(self.ticks(), set())


if __name__ == "__main__":
    unittest.main()
