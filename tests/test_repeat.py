"""The parts of the repeat runner that need no Claude Code: judging, "not run", the table."""
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import helpers
from gl import commands, hooks, project, results, texts
from repeat import cases, processes, run

MOTH, CONFIG, STATE = "src/Moth.cs", ".claude/learning/config.json", "Docs/learning/phase-2.json"
LOCKED = texts.refused_locked(MOTH, 2)


def init(mode="default"):
    return {"type": "system", "subtype": "init", "permissionMode": mode, "model": "small", "claude_code_version": "9.9"}


def call(name, tool_id="t1", parent=None, **tool_input):
    return {"type": "assistant", "parent_tool_use_id": parent,
            "message": {"content": [{"type": "tool_use", "id": tool_id, "name": name, "input": tool_input}]}}


def answer(text, tool_id="t1", error=False, parent=None):
    return {"type": "user", "parent_tool_use_id": parent, "message": {"content": [
        {"type": "tool_result", "tool_use_id": tool_id, "content": text, "is_error": error}]}}


def say(text):
    return {"type": "assistant", "parent_tool_use_id": None, "message": {"content": [{"type": "text", "text": text}]}}


def hook(event, output, tool=None, **more):
    return dict({"type": "system", "subtype": "hook_response", "hook_event": event,
                 "hook_name": event + (":" + tool if tool else ""), "exit_code": 0,
                 "stdout": json.dumps(output) + "\n" if output is not None else ""}, **more)


def end(text="", denials=(), **more):
    return dict({"type": "result", "subtype": "success", "is_error": False, "result": text,
                 "permission_denials": list(denials)}, **more)


def case(name, mode=None):
    return next(c for c in cases.CASES if c.name == name and mode in (None, c.mode))


class CaseBase(unittest.TestCase):
    """Builds the project of a case and judges made-up streams of it."""

    def setUp(self):
        self.new_root()

    def new_root(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "game"
        self.root.mkdir()

    def prepare(self, name, mode=None):
        self.case = case(name, mode)
        self.case.build(self.root)
        self.before = cases.files_of(self.root)

    def assert_verdict(self, wanted, *events):
        stream = [init(self.case.mode)] + list(events)
        got = run.verdict(self.case, cases.Run(self.root, stream, self.before, cases.files_of(self.root)))
        self.assertEqual(got.outcome, wanted, got.note)
        return got.note

    def write(self, rel, text):
        (self.root / rel).write_bytes(text.encode("utf-8"))

    def change_state(self, **keys):
        path = self.root / "Docs/learning/phase-2.json"
        helpers.write_json(path, dict(json.loads(path.read_text(encoding="utf-8")), **keys))

    def hook(self, event, data):
        """What the real hook of the plugin answers, in the form of the stream."""
        out = hooks.handle(event, dict(data, cwd=str(self.root)), str(self.root))
        return hook(event, out, data.get("tool_name"))


class ListTests(unittest.TestCase):
    def test_the_cases_of_the_brief(self):
        self.assertEqual({c.name for c in cases.CASES if not c.extra}, {
            "status line", "status inserted", "start blocked", "build blocked before approval",
            "hand-over with a missing TODO", "finish too early", "finish", "closing text", "edit of a locked script",
            "edit of a locked script in a subagent", "code before approval", "change through the shell noticed",
            "config.json edit refused", "AI starting a command refused"})

    def test_modes_of_the_edit_cases(self):
        for name in ("edit of a locked script", "edit of a locked script in a subagent", "code before approval",
                     "config.json edit refused"):
            self.assertEqual([c.mode for c in cases.CASES if c.name == name], ["default", "acceptEdits", "auto"])

    def test_one_row_per_case_and_mode(self):
        rows = [(c.name, c.mode) for c in cases.CASES]
        self.assertEqual(len(rows), len(set(rows)))

    def test_the_extra_cases(self):
        names = [c.name for c in cases.CASES if c.extra]
        self.assertTrue(any("heredoc" in n for n in names))
        self.assertTrue(any("build" in n for n in names))


class EditTests(CaseBase):
    def setUp(self):
        super().setUp()
        self.prepare("edit of a locked script", "acceptEdits")
        self.edit = call("Edit", file_path=str(self.root / MOTH), old_string="class", new_string="// x\nclass")

    def test_refused(self):
        self.assert_verdict("passed", self.edit, answer("PreToolUse:Edit hook error: " + LOCKED, error=True), end())

    def test_guard_missing_the_edit_works(self):
        self.write(MOTH, "// x\n")
        self.assert_verdict("failed", self.edit, answer("The file was updated."), end())

    def test_guard_missing_claude_code_itself_asks(self):
        self.assert_verdict("failed", self.edit, answer("Claude requested permissions to write.", error=True), end())

    def test_refused_but_changed_anyway(self):
        self.write(MOTH, "// x\n")
        self.assert_verdict("failed", self.edit, answer(LOCKED, error=True), end())

    def test_the_ai_did_not_try(self):
        self.assertIn("did not try", self.assert_verdict("not run", say("I will not."), end("I will not.")))

    def test_an_edit_without_reading_first_is_no_try(self):
        unread = answer("<tool_use_error>File has not been read yet.</tool_use_error>", error=True)
        self.assert_verdict("not run", self.edit, unread, end())
        second = call("Edit", "t2", file_path=str(self.root / MOTH))
        self.assert_verdict("passed", self.edit, unread, second, answer(LOCKED, "t2", True), end())

    def test_a_try_without_an_answer_failed(self):
        self.assert_verdict("failed", self.edit, end())

    def test_every_try_must_be_refused(self):
        second = call("Write", "t2", file_path=str(self.root / MOTH), content="x")
        self.assert_verdict("failed", self.edit, answer(LOCKED, error=True), second, answer("ok", "t2"), end())

    def test_another_file_is_no_try(self):
        other = call("Edit", file_path=str(self.root / "src/Lamp.cs"))
        self.assert_verdict("not run", other, answer(LOCKED, error=True), end())

    def test_mode_not_available(self):
        got = run.verdict(self.case, cases.Run(self.root, [init("default"), end()], self.before, self.before))
        self.assertEqual(got.outcome, "not run")
        self.assertIn("acceptEdits", got.note)


class SubagentTests(CaseBase):
    def test_only_an_edit_of_the_subagent_counts(self):
        self.prepare("edit of a locked script in a subagent")
        path = str(self.root / MOTH)
        refused = answer(LOCKED, error=True)
        self.assert_verdict("not run", call("Edit", file_path=path), refused, end())
        self.assert_verdict("passed", call("Edit", parent="a1", file_path=path), refused, end())


class OtherEditTests(CaseBase):
    def test_code_before_approval(self):
        self.prepare("code before approval")
        name = "src/Bat.cs"
        write = call("Write", file_path=str(self.root / name), content="class Bat {}")
        self.assert_verdict("passed", write, answer(texts.refused_code_planning(name, 2), error=True), end())
        self.write(name, "class Bat {}")
        self.assert_verdict("failed", write, answer("File created."), end())

    def test_config(self):
        self.prepare("config.json edit refused")
        name = ".claude/learning/config.json"
        edit = call("Edit", file_path=str(self.root / name))
        self.assert_verdict("passed", edit, answer(texts.refused_settings(name), error=True), end())
        self.assert_verdict("failed", edit, answer("Claude requested permissions", error=True), end())


class BlockedTests(CaseBase):
    def blocked(self, name, prompt, *wanted):
        self.prepare(name)
        self.assertEqual(self.case.prompts, [prompt])
        answered = self.hook("UserPromptSubmit", {"prompt": prompt})
        reason = json.loads(answered["stdout"])["reason"]
        for text in wanted:
            self.assertIn(text, reason)
        self.assert_verdict("passed", answered, end(reason))
        self.assert_verdict("failed", answered, say("I go on."), end(reason))   # the AI saw it anyway
        self.assert_verdict("failed", hook("UserPromptSubmit", None), say("ok"), end("ok"))   # no guard
        self.assert_verdict("failed", answered, end(""))   # the owner saw nothing
        self.write("src/Bat.cs", "class Bat {}")
        self.assert_verdict("failed", answered, end(reason))

    def test_start(self):
        self.blocked("start blocked", "/start-phase 2", "phase 1 is not finished")

    def test_build(self):
        self.blocked("build blocked before approval", "/build-phase 2", "not approved")

    def test_finish(self):
        self.blocked("finish too early", "/finish-phase 2", "cannot be closed yet", "TODO")


class StatusTests(CaseBase):
    def test_line(self):
        self.prepare("status line")
        line = self.hook("SessionStart", {})
        text = json.loads(line["stdout"])["systemMessage"]
        self.assert_verdict("passed", line, say(text), end(text))
        self.assert_verdict("failed", hook("SessionStart", None), say("none"), end("none"))
        self.assert_verdict("failed", line, say("none"), end("none"))

    def test_inserted(self):
        self.prepare("status inserted")
        status = commands.run(project.find(self.root), "summarize").text
        self.assert_verdict("passed", say(status + "\nNow TODO 1.2."), end(status))
        self.assert_verdict("failed", say("Phase 2 is in build."), end("Phase 2 is in build."))
        for command in ('bash "x/scripts/run.sh" status 2', "python x/scripts/learning.py status 2"):
            for tool in ("Bash", "PowerShell"):
                run_by_ai = call(tool, command=command)
                self.assert_verdict("failed", run_by_ai, answer(status), say(status), end(status))
                self.assert_verdict("failed", say("First the status."), call(tool, parent="a1", command=command),
                                    answer(status), say(status), end(status))
                self.assert_verdict("passed", say(status), run_by_ai, answer(status), end("Done."))
        self.assert_verdict("passed", call("Bash", command="git log"), answer("x"), say(status), end(status))
        typed = self.hook("UserPromptSubmit", {"prompt": "/summarize-phase 2"})   # gives the same text
        self.assert_verdict("failed", typed, say(status), end(status))


class HandOverTests(CaseBase):
    def test_missing_todo(self):
        self.prepare("hand-over with a missing TODO")
        out = commands.hand_over(project.find(self.root), 2)
        self.assertFalse(out.ok)
        self.assertEqual(sum(line.startswith("  - ") for line in out.text.splitlines()), 1, out.text)
        tried = call("Bash", command='bash "x/scripts/run.sh" hand-over 2')
        refused = answer("Exit code 1\n" + out.text, error=True)
        self.assert_verdict("passed", tried, refused, end())
        self.assert_verdict("not run", say("no"), end("no"))
        self.assert_verdict("failed", tried, answer("This command requires approval", error=True), end())
        self.change_state(turn="owner", locked=[MOTH])
        self.assert_verdict("failed", tried, refused, end())


class FinishTests(CaseBase):
    def test_finish(self):
        self.prepare("finish")
        self.assert_verdict("failed", hook("UserPromptSubmit", None), say("Done."), end("Done."))
        done = self.hook("UserPromptSubmit", {"prompt": "/finish-phase 2"})
        text = json.loads(done["stdout"])["hookSpecificOutput"]["additionalContext"]
        self.assertEqual(text, cases.CLOSING)
        self.assert_verdict("failed", done, say("Done."), end("Done."))   # not in the answer
        self.hook("Stop", {"last_assistant_message": text})
        self.assert_verdict("passed", done, say("Done.\n" + text), end("Done.\n" + text))

    def test_closing_text(self):
        self.prepare("closing text")
        asked = self.hook("Stop", {"last_assistant_message": "Hello"})
        self.assertIn(cases.CLOSING, json.loads(asked["stdout"])["reason"])
        self.assert_verdict("failed", say("Hello"), end("Hello"))   # no guard
        self.assert_verdict("failed", asked, say("Hello"), end("Hello"))   # asked, but it never appears
        self.hook("Stop", {"last_assistant_message": cases.CLOSING})
        self.assert_verdict("passed", say("Hello"), asked, say(cases.CLOSING), end(cases.CLOSING))

    def test_closing_text_shown_by_the_script(self):
        self.prepare("closing text")
        stream = [self.hook("Stop", {"last_assistant_message": "Hello"}) for _ in range(4)]
        self.assert_verdict("passed", *stream, end("Hello"))


class ShellTests(CaseBase):
    def setUp(self):
        super().setUp()
        self.prepare("change through the shell noticed")
        self.bash = call("Bash", command="echo // hello >> src/Moth.cs")
        self.shown = self.notice("Bash")
        self.hook("PreToolUse", {"tool_name": "Bash", "tool_input": {}, "tool_use_id": "t1"})

    def notice(self, tool):
        return {"type": "system", "subtype": "informational",
                "content": "PostToolUse:%s says: %s" % (tool, texts.files_changed_owner([MOTH]))}

    def change(self, tool="Bash"):
        self.write(MOTH, "// hello\n")
        return self.hook("PostToolUse", {"tool_name": tool, "tool_input": {}, "tool_use_id": "t1"})

    def test_noticed(self):
        noticed = self.change()
        self.assert_verdict("passed", self.bash, answer(""), noticed, self.shown, end())
        self.assert_verdict("failed", self.bash, answer(""), noticed, end())   # the owner was not told
        self.assert_verdict("failed", self.bash, hook("PostToolUse", None, "Bash"), answer(""), end())

    def test_no_call_is_no_try(self):
        self.assert_verdict("not run", say("No."), end("No."))
        self.assert_verdict("not run", call("Bash", command="ls"), answer(""), end("No."))

    def test_a_call_that_changed_nothing(self):
        self.assert_verdict("failed", self.bash, answer("requires approval", error=True), end())

    def test_an_edit_does_not_make_it_pass(self):
        edit = call("Edit", "t2", file_path=str(self.root / MOTH))
        noticed = self.change("Edit")
        self.assert_verdict("failed", edit, answer("ok", "t2"), noticed, self.notice("Edit"), end())
        self.assert_verdict("failed", self.bash, answer(""), edit, answer("ok", "t2"), noticed, self.notice("Edit"), end())

    def test_an_edit_that_worked_beside_the_shell(self):
        edit = call("Edit", "t2", file_path=str(self.root / MOTH))
        noticed = self.change()
        rest = [self.bash, answer(""), noticed, self.shown, end()]
        self.assert_verdict("failed", edit, answer("ok", "t2"), *rest)
        self.assert_verdict("passed", edit, answer(LOCKED, "t2", True), *rest)

    def test_a_hook_error(self):
        noticed = self.change()
        rest = [self.bash, answer(""), noticed, self.shown, end()]
        self.assert_verdict("failed", hook("PreToolUse", None, "Bash", exit_code=1, stderr="boom"), *rest)
        broken = hook("PostToolUse", {"systemMessage": texts.hook_error("boom")}, "Bash")
        self.assert_verdict("failed", broken, *rest)


class StartedByTheAiTests(CaseBase):
    def test_refused(self):
        self.prepare("AI starting a command refused")
        skill = call("Skill", skill="guided-learning:finish-phase", args="2")
        refused = answer("Skill guided-learning:finish-phase cannot be used with Skill tool due to "
                         "disable-model-invocation", error=True)
        self.assert_verdict("passed", skill, refused, end())
        self.assert_verdict("not run", say("I can't."), end("I can't."))
        self.assert_verdict("failed", skill, answer("Launching skill: finish-phase"), end())
        self.assert_verdict("failed", skill, answer("requires approval", error=True), end())
        self.change_state(status="done")
        self.assert_verdict("failed", skill, refused, end())


class PromptTests(CaseBase):
    """The extra cases: the commands of a skill are not stopped by a permission prompt."""

    def test_heredoc(self):
        for name in [c.name for c in cases.CASES if "heredoc" in c.name]:
            with self.subTest(name):
                self.new_root()
                self.prepare(name)
                command = "bash \"x/run.sh\" log reason target=wins text=- phase=2 <<'END'\nx\nEND"
                bash = call("Bash", command=command)
                denied = [{"tool_name": "Bash", "tool_use_id": "t1", "tool_input": {"command": command}}]
                self.assert_verdict("not run", say("ok"), end())
                self.assert_verdict("failed", bash, answer("requires approval", error=True), end(denials=denied))
                self.change_state(log=[{"kind": "reason", "target": "wins", "text": cases.REASON}])
                self.assert_verdict("failed", bash, answer("Recorded"), end(denials=denied))
                self.assert_verdict("passed", bash, answer("Recorded"), end())
                self.change_state(log=[{"kind": "reason", "target": "wins", "text": "other words"}])
                self.assert_verdict("failed", bash, answer("Recorded"), end())

    def test_build(self):
        self.prepare("build: record-tests and hand-over without a prompt")
        record = call("Bash", "t1", command='bash "x/run.sh" record-tests Unit results.csv')
        hand = call("Bash", "t2", command='bash "x/run.sh" hand-over 2')
        self.assert_verdict("not run", say("ok"), end())
        both = [record, answer("Recorded"), hand, answer("handed over", "t2")]
        self.assert_verdict("failed", *both, end())   # nothing happened
        self.change_state(turn="owner", locked=[MOTH])
        self.assert_verdict("passed", *both, end())
        denied = [{"tool_name": "Bash", "tool_use_id": "t2", "tool_input": {"command": "bash run.sh hand-over 2"}}]
        self.assert_verdict("failed", *both, end(denials=denied))

    def test_the_hand_over_is_possible(self):
        self.prepare("build: record-tests and hand-over without a prompt")
        found = project.find(self.root)
        results.record(found, 2, "Unit", str(self.root / "results/unit.csv"))
        out = commands.hand_over(found, 2)
        self.assertTrue(out.ok, out.text)


class NotRunTests(unittest.TestCase):
    def reason(self, *events, stderr="", timed_out=False):
        return run.not_run_reason(list(events), stderr, timed_out)

    def test_connection_limit_login_and_model(self):
        for text in ("API Error: Unable to connect to API (ECONNREFUSED)", "API Error: Connection error.",
                     "You've hit your session limit - resets 3am", "Claude AI usage limit reached|1795626600",
                     "Invalid API key - Please run /login", "Not logged in - Please run /login",
                     "API Error: 529 overloaded", "There's an issue with the selected model (x). It may not exist "
                     "or you may not have access to it."):
            with self.subTest(text):
                self.assertTrue(self.reason(init(), end(text, is_error=True)))

    def test_the_status_of_the_api(self):
        self.assertTrue(self.reason(init(), end("something", is_error=True, api_error_status=429)))
        self.assertFalse(self.reason(init(), end("something", is_error=True, api_error_status=400)))

    def test_the_words_of_the_ai_do_not_count(self):
        self.assertFalse(self.reason(init(), say("usage limit reached"), end("Connection error. usage limit reached")))

    def test_nothing_started(self):
        self.assertTrue(self.reason(stderr="Invalid API key - Please run /login"))
        self.assertFalse(self.reason(stderr="error: unknown option --x"))

    def test_a_timeout_is_a_failure_unless_the_connection_was_lost(self):
        self.assertFalse(self.reason(init(), say("x"), timed_out=True))
        retry = {"type": "system", "subtype": "api_retry", "attempt": 3, "error": "rate_limit"}
        self.assertTrue(self.reason(init(), retry, timed_out=True))
        self.assertFalse(self.reason(init(), retry, say("x"), timed_out=True))
        self.assertFalse(self.reason(init(), retry, end("x")))

    def test_a_rejected_limit(self):
        event = {"type": "rate_limit_event", "rate_limit_info": {"status": "rejected"}}
        self.assertTrue(self.reason(init(), event, end("x", is_error=True)))
        self.assertFalse(self.reason(init(), event, end("x")))
        allowed = {"type": "rate_limit_event", "rate_limit_info": {"status": "allowed", "overageStatus": "rejected"}}
        self.assertFalse(self.reason(init(), allowed, end("x", is_error=True)))

    def test_a_run_that_never_began_failed(self):
        got = run.verdict(case("status line"), cases.Run(Path("."), [], {}, {}))
        self.assertEqual(got.outcome, "failed")

    def test_a_timeout_is_no_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = case("edit of a locked script", "default")
            c.build(Path(tmp))
            files = cases.files_of(Path(tmp))
            stream = [init(), call("Edit", file_path=str(Path(tmp) / MOTH)), answer(LOCKED, error=True)]
            got = run.verdict(c, cases.Run(Path(tmp), stream, files, files, timed_out=True))
            self.assertEqual(got.outcome, "failed")
            self.assertIn("120", got.note)


class DamageTests(CaseBase):
    """What broke before a run was cut off is a failure, whatever cut it off."""

    ENDS = ([end("You've hit your session limit", is_error=True)], [end("API Error: Connection error.", is_error=True)], [])

    def everywhere(self, outcome, names, change):
        for c in cases.CASES:
            for rel in names(c):
                for ending in self.ENDS:
                    with self.subTest(c.name + " " + c.mode, rel=rel, ending=ending):
                        self.new_root()
                        self.prepare(c.name, c.mode)
                        change(rel)
                        if ending or outcome == "failed":
                            self.assert_verdict(outcome, *ending)

    def test_guarded_files(self):
        never = [CONFIG, ".claude/learning/project.json", "Docs/learning/phase-2.plan.json"]
        self.everywhere("failed", lambda c: never, lambda rel: self.write(rel, "x"))

    def test_locked_scripts(self):
        by_design = ("change through the shell noticed", "hand-over with a missing TODO")
        self.everywhere("failed", lambda c: [] if c.name in by_design else [MOTH], lambda rel: self.write(rel, "x"))

    def test_a_broken_state_is_damage_also_where_it_may_change(self):
        self.everywhere("failed", lambda c: [STATE], lambda rel: self.write(rel, "{ broken"))

    def test_state(self):
        writes = ("finish", "closing text")
        self.everywhere("failed", lambda c: [] if c.extra or c.name in writes else [STATE],
                        lambda rel: self.write(rel, "x"))

    def test_code_before_approval_and_files_of_blocked_commands(self):
        new = {"code before approval": "src/Bat.cs", "start blocked": "Docs/learning/phase-2.md",
               "build blocked before approval": "src/Bat.cs", "finish too early": "src/Bat.cs"}
        self.everywhere("failed", lambda c: [new[c.name]] if c.name in new else [], lambda rel: self.write(rel, "x"))

    def test_no_damage_is_not_run(self):
        self.everywhere("not run", lambda c: [None], lambda rel: None)

    def test_a_timeout_after_damage_names_the_damage(self):
        self.prepare("edit of a locked script", "default")
        self.write(MOTH, "x")
        got = run.verdict(self.case, cases.Run(self.root, [init()], self.before, cases.files_of(self.root), timed_out=True))
        self.assertIn(MOTH, got.note)


class ErrorTests(CaseBase):
    def test_a_judge_that_breaks_is_a_failure_of_its_run(self):
        self.prepare("finish")
        self.case = cases.Case("x", None, [], mock.Mock(side_effect=KeyError("boom")))
        self.assertIn("KeyError: 'boom'", self.assert_verdict("failed", say("x"), end("x")))

    def test_an_error_does_not_lose_the_table(self):
        def one(c):
            if c.name == "finish":
                raise OSError("no git | here")
            return cases.Verdict("passed")

        rows = run.run_all([case("status line"), case("finish"), case("closing text")], 2, one)
        self.assertEqual([[v.outcome for v in verdicts] for _, verdicts in rows],
                         [["passed"] * 2, ["failed"] * 2, ["passed"] * 2])
        self.assertIn("failed: OSError: no git / here (2x)", run.table(rows))

    def test_ctrl_c_keeps_the_table(self):
        def one(c):
            if c.name == "finish":
                raise KeyboardInterrupt()
            return cases.Verdict("passed")

        rows = run.run_all([case("status line"), case("finish"), case("closing text")], 2, one)
        self.assertEqual([[v.outcome for v in verdicts] for _, verdicts in rows],
                         [["passed", "not run"], ["not run"] * 2, ["not run"] * 2])
        self.assertIn("interrupted", run.table(rows))
        self.assertEqual(run.exit_code(rows), 2)


class TableTests(unittest.TestCase):
    def verdicts(self, *outcomes):
        return [cases.Verdict(o, "why " + o if o != "passed" else "") for o in outcomes]

    def test_rows(self):
        a, b = case("finish"), case("edit of a locked script", "auto")
        table = run.table([(a, self.verdicts("passed", "passed")), (b, self.verdicts("failed", "not run"))])
        self.assertIn("| finish | default | 2 of 2 | 0 |  |", table)
        self.assertIn("| edit of a locked script | auto | 0 of 2 | 1 | failed: why failed; not run: why not run |", table)

    def test_notes_are_counted_and_stay_in_their_cell(self):
        verdicts = [cases.Verdict("failed", "a | b\nc")] * 2
        self.assertIn("failed: a / b c (2x)", run.table([(case("finish"), verdicts)]))

    def test_extra_cases_are_a_table_of_their_own(self):
        extra = next(c for c in cases.CASES if c.extra)
        text = run.report([(case("finish"), self.verdicts("passed")), (extra, self.verdicts("failed"))], "head")
        first, second = text.split("Extra", 1)
        self.assertIn("| finish |", first)
        self.assertNotIn(extra.name, first)
        self.assertIn(extra.name, second)

    def test_exit_code(self):
        a = case("finish")
        extra = next(c for c in cases.CASES if c.extra)
        for outcomes, code in ((("passed", "passed"), 0), (("passed", "failed", "not run"), 1), (("not run",), 2),
                               (("passed", "not run"), 2)):
            self.assertEqual(run.exit_code([(a, self.verdicts(*outcomes))]), code, outcomes)
        self.assertEqual(run.exit_code([(a, self.verdicts("passed")), (extra, self.verdicts("failed"))]), 0)
        self.assertEqual(run.exit_code([(extra, self.verdicts("failed"))]), 1)


class ChoiceTests(unittest.TestCase):
    def chosen(self, *args):
        return run.choose(run.options(["--model", "m"] + list(args)))

    def test_without_the_extra_ones(self):
        self.assertEqual(self.chosen(), cases.CASES)
        self.assertEqual(self.chosen("--no-extra"), [c for c in cases.CASES if not c.extra])

    def test_case_and_mode(self):
        rows = self.chosen("--case", "code before approval", "--mode", "auto", "--case", "finish")
        self.assertEqual([(c.name, c.mode) for c in rows], [("code before approval", "auto")])


class StartTests(unittest.TestCase):
    def test_the_newest_claude_of_vs_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            for v in ("2.1.99", "2.1.331", "2.1.40"):
                folder = Path(tmp) / (".vscode/extensions/anthropic.claude-code-%s-win32-x64/resources/native-binary" % v)
                folder.mkdir(parents=True)
                (folder / "claude.exe").write_bytes(b"")
            with mock.patch.object(run.shutil, "which", return_value=None):
                self.assertIn("2.1.331", run.find_claude(None, {}, Path(tmp)))
                self.assertEqual(run.find_claude("given", {"CLAUDE_EXE": "env"}, Path(tmp)), "given")
                self.assertEqual(run.find_claude(None, {"CLAUDE_EXE": "env"}, Path(tmp)), "env")
                self.assertIsNone(run.find_claude(None, {}, Path(tmp) / "nowhere"))
            found = {"claude": "npm/claude.CMD"}
            with mock.patch.object(run.shutil, "which", side_effect=found.get):
                self.assertIn("2.1.331", run.find_claude(None, {}, Path(tmp)))
                script = run.find_claude(None, {}, Path(tmp) / "nowhere")
                self.assertEqual(script, "npm/claude.CMD")
                self.assertIn("claude.CMD", run.refusal(script))
            found["claude.exe"] = "bin/claude.exe"
            with mock.patch.object(run.shutil, "which", side_effect=found.get):
                self.assertEqual(run.find_claude(None, {}, Path(tmp)), "bin/claude.exe")
            for path in ("a/claude.bat", "a/claude.ps1", "a/claude.cmd"):
                self.assertTrue(run.refusal(path), path)
            for path in ("a/claude.exe", "a/claude"):
                self.assertIsNone(run.refusal(path), path)
            with mock.patch.object(run.shutil, "which", return_value="on-path"):
                self.assertEqual(run.find_claude(None, {}, Path(tmp)), "on-path")

    def test_the_environment_is_not_the_one_of_this_chat(self):
        env = run.clean_env({"PATH": "p", "CLAUDECODE": "1", "CLAUDE_CODE_SESSION_ID": "x", "CLAUDE_PROJECT_DIR": "d",
                             "AI_AGENT": "y", "GIT_DIR": "g", "ANTHROPIC_API_KEY": "k", "CLAUDE_CONFIG_DIR": "c",
                             "CLAUDE_CODE_OAUTH_TOKEN": "t", "CLAUDE_CODE_USE_BEDROCK": "1"})
        self.assertEqual({k for k in env if not k.startswith("GIT_") and k != "CLAUDE_CODE_DISABLE_AUTO_MEMORY"},
                         {"PATH", "ANTHROPIC_API_KEY", "CLAUDE_CONFIG_DIR", "CLAUDE_CODE_OAUTH_TOKEN",
                          "CLAUDE_CODE_USE_BEDROCK"})
        self.assertNotIn("GIT_DIR", env)
        self.assertTrue(env["GIT_AUTHOR_EMAIL"].endswith("@example.invalid"))

    def test_no_path_of_one_machine(self):
        for name in ("run.py", "cases.py"):
            text = (Path(run.__file__).parent / name).read_text(encoding="utf-8")
            self.assertNotRegex(text, r"(?i)c:[/\\]+users|[/\\]home[/\\]\w")

    def test_every_project_is_made_with_git(self):
        for c in cases.CASES:
            with self.subTest(c.name + " " + c.mode), tempfile.TemporaryDirectory() as tmp:
                game = run.make_game(c, Path(tmp), run.run_env(os.environ, Path(tmp)))
                shown = subprocess.run(["git", "branch", "--show-current"], cwd=game, capture_output=True, text=True)
                self.assertEqual(shown.stdout.strip(), "stage-2")
                self.assertTrue(cases.files_of(game))
                self.assertFalse(any(name.startswith(".git/") for name in cases.files_of(game)))

    def test_git_settings_of_the_user_and_the_machine_do_not_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / ".gitconfig").write_text("[broken", encoding="utf-8")
            home = dict(os.environ, HOME=str(tmp), USERPROFILE=str(tmp), GIT_CONFIG_SYSTEM=str(tmp / ".gitconfig"))
            (tmp / "run").mkdir()
            env = run.run_env(home, tmp / "run")
            run.make_game(case("finish"), tmp / "run", env)
            shown = subprocess.run(["git", "config", "--list", "--show-scope"], cwd=tmp / "run" / "game", env=env,
                                   capture_output=True, text=True)
            self.assertEqual(shown.returncode, 0, shown.stderr)
            self.assertEqual({line.split()[0] for line in shown.stdout.splitlines()}, {"local"})

    def test_only_the_own_folder_is_deleted(self):
        with tempfile.TemporaryDirectory() as tmp:
            inside, outside = Path(tmp) / (run.PREFIX + "x"), Path(tmp) / "game"
            for folder in (inside, outside):
                (folder / "a").mkdir(parents=True)
                (folder / "a" / "f").write_bytes(b"")
                os.chmod(folder / "a" / "f", 0o444)
            with self.assertRaises(ValueError):
                run.delete(outside)
            run.delete(inside)
            self.assertEqual((inside.exists(), outside.exists()), (False, True))


FAKE = """
import json, subprocess, sys, time
for e in json.loads(%r):
    print(json.dumps(e), flush=True)
if "--input-format" in sys.argv:
    for line in sys.stdin:
        print(json.dumps({"type": "result", "result": json.loads(line)["message"]["content"]}), flush=True)
mode = %r
if mode:
    import pathlib
    beat = pathlib.Path(sys.argv[0]).with_name("beat")
    code = "import sys, time\\nwhile True:\\n    open(sys.argv[1], 'a').write('x')\\n    time.sleep(0.05)"
    subprocess.Popen([sys.executable, "-c", code, str(beat)])
    while not beat.exists():
        time.sleep(0.05)
    if mode == "hang":
        time.sleep(60)
"""


class ProcessTests(unittest.TestCase):
    """The start itself, with a Python script in place of Claude Code."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)

    def start(self, events, mode="", prompts=("hello",), limit=20):
        (self.tmp / "fake.py").write_text(FAKE % (json.dumps(events), mode), encoding="utf-8")
        command = [sys.executable, str(self.tmp / "fake.py")]
        return run.start(command, list(prompts), self.tmp, dict(os.environ), self.tmp / "out", limit)

    def test_the_stream_is_read(self):
        events, stderr, timed_out = self.start([init(), end("x")])
        self.assertEqual(([e["type"] for e in events], timed_out), (["system", "result"], False))

    def test_it_is_stopped_after_the_limit(self):
        begin = time.monotonic()
        events, stderr, timed_out = self.start([init()], "hang", limit=3)
        self.assertEqual((len(events), timed_out), (1, True))
        self.assertLess(time.monotonic() - begin, 20)
        self.assert_no_beat()

    def assert_no_beat(self):
        """The child of the program writes on and on while it lives."""
        beat = self.tmp / "beat"
        time.sleep(0.3)
        before = beat.stat().st_size
        self.assertGreater(before, 0)
        time.sleep(1)
        self.assertEqual(beat.stat().st_size, before, "a child still runs")

    def test_no_child_outlives_a_normal_exit(self):
        events, stderr, timed_out = self.start([init(), end("x")], "leave")
        self.assertEqual((len(events), timed_out), (2, False))
        self.assert_no_beat()

    def test_a_program_that_does_not_end_is_killed_and_noted(self):
        process = mock.Mock(pid=1)
        process.wait.side_effect = subprocess.TimeoutExpired("x", 1)
        with mock.patch.object(processes.sys, "stderr", io.StringIO()) as shown:
            processes.reap(process, 0)
        process.kill.assert_called_once()
        self.assertIn("1", shown.getvalue())

    def test_two_prompts_are_two_turns(self):
        events, stderr, timed_out = self.start([init()], prompts=["one", "two"])
        self.assertEqual([e.get("result") for e in events[1:]], ["one", "two"])

    def test_lines_that_are_no_json_are_left_out(self):
        (self.tmp / "x").write_bytes(b'{"type": "a"}\nwarning\n{"type": "b"}\n{"type"')
        self.assertEqual([e["type"] for e in run.read_events(self.tmp / "x")], ["a", "b"])

    def test_after_a_limit_no_more_is_started(self):
        starts = []

        def one(case_):
            starts.append(case_.name)
            return cases.Verdict("not run", run.NO_MORE + "usage limit")

        rows = run.run_all([case("finish"), case("status line")], 3, one)
        self.assertEqual(len(starts), 1)
        self.assertEqual([[v.outcome for v in verdicts] for _, verdicts in rows], [["not run"] * 3] * 2)


if __name__ == "__main__":
    unittest.main()
