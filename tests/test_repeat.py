"""The parts of the repeat runner that need no Claude Code: judging, "not run", the table."""
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
from repeat import cases, run

MOTH = "src/Moth.cs"
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


def hook(event, output):
    return {"type": "system", "subtype": "hook_response", "hook_event": event,
            "stdout": json.dumps(output) + "\n" if output is not None else ""}


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
        return hook(event, hooks.handle(event, dict(data, cwd=str(self.root)), str(self.root)))


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
    def test_noticed(self):
        self.prepare("change through the shell noticed")
        self.hook("PreToolUse", {"tool_name": "Bash", "tool_input": {}, "tool_use_id": "t1"})
        bash = call("Bash", command="echo // hello >> src/Moth.cs")
        self.assert_verdict("not run", say("No."), end("No."))
        self.write(MOTH, "// hello\n")
        noticed = self.hook("PostToolUse", {"tool_name": "Bash", "tool_input": {}, "tool_use_id": "t1"})
        shown = {"type": "system", "subtype": "informational",
                 "content": "PostToolUse:Bash says: " + texts.files_changed_owner([MOTH])}
        self.assert_verdict("passed", bash, answer(""), noticed, shown, end())
        self.assert_verdict("failed", bash, answer(""), noticed, end())   # the owner was not told
        self.assert_verdict("failed", bash, hook("PostToolUse", None), answer(""), end())


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
                game = run.make_game(c, Path(tmp), run.clean_env(os.environ))
                shown = subprocess.run(["git", "branch", "--show-current"], cwd=game, capture_output=True, text=True)
                self.assertEqual(shown.stdout.strip(), "stage-2")
                self.assertTrue(cases.files_of(game))
                self.assertFalse(any(name.startswith(".git/") for name in cases.files_of(game)))

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
if %r:
    subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    time.sleep(60)
"""


class ProcessTests(unittest.TestCase):
    """The start itself, with a Python script in place of Claude Code."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)

    def start(self, events, hang=False, prompts=("hello",), limit=20):
        (self.tmp / "fake.py").write_text(FAKE % (json.dumps(events), hang), encoding="utf-8")
        command = [sys.executable, str(self.tmp / "fake.py")]
        return run.start(command, list(prompts), self.tmp, dict(os.environ), self.tmp / "out", limit)

    def test_the_stream_is_read(self):
        events, stderr, timed_out = self.start([init(), end("x")])
        self.assertEqual(([e["type"] for e in events], timed_out), (["system", "result"], False))

    def test_it_is_stopped_after_the_limit(self):
        begin = time.monotonic()
        events, stderr, timed_out = self.start([init()], hang=True, limit=2)
        self.assertEqual((len(events), timed_out), (1, True))
        self.assertLess(time.monotonic() - begin, 20)

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
