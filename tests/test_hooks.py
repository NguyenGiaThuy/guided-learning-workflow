import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import helpers
from helpers import FULL_MD, TEST_CODE, full_plan, shell, suite_result
from gl import commands, hooks, log, project, render, results, state, store, texts

ROOT = Path(__file__).resolve().parent.parent
MOTH = shell(["1.1", "1.2"])


def find_bash():
    """A bash that runs run.sh by its absolute path, as hooks.json does. On Windows the first one
    in the path may be that of WSL, which does not know drive letters; then the one of git is used."""
    git = shutil.which("git")
    places = [shutil.which("bash")] + [str(d / "bin" / "bash.exe") for d in (Path(git).parents if git else [])]
    for bash in places:
        if not bash or not os.path.exists(bash):
            continue
        try:
            done = subprocess.run([bash, RUN_SH, "version"], timeout=60, stdin=subprocess.DEVNULL,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except (OSError, subprocess.SubprocessError):
            continue
        if done.returncode == 0:
            return bash
    return None


RUN_SH = (ROOT / "scripts" / "run.sh").as_posix()
BASH = find_bash()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(os.path.realpath(tempfile.mkdtemp()))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = self.tmp / "game"
        for name, fn in (("current_branch", lambda p: "stage-2"), ("is_merged", lambda p, b: True)):
            patcher = mock.patch.object(state, name, side_effect=fn)
            patcher.start()
            self.addCleanup(patcher.stop)

    # --- fixtures ---

    def make(self, stored=None, files=None, plan=None, n=2, settings=None, root=None):
        root = root or self.root
        st = {"status": "build", "turn": "owner", "part": 0, "locked": ["src/Moth.cs"]}
        st.update(stored or {})
        st = {k: v for k, v in st.items() if v is not None}
        helpers.make_project(root, phases={n: {"state": st, "plan": plan or full_plan(n), "md": FULL_MD}},
                             files=files if files is not None else {"src/Moth.cs": MOTH, "src/Other.cs": "class O {}\n"},
                             settings=settings)
        return project.find(root)

    def rehearse(self, stored=None):
        """Switch rehearsal on, with a fake project of one locked file."""
        fake = self.root / ".claude" / "learning" / "rehearsal"
        self.make(stored or {"locked": ["src/Fake.cs"]}, files={"src/Fake.cs": MOTH}, root=fake)
        helpers.set_switch(self.root, '{"rehearsal": true}')
        helpers.mark_seen(self.root)
        return fake

    def data(self, n=2, root=None):
        return store.read((root or self.root) / "Docs" / "learning" / ("phase-%d.json" % n))

    def files(self):
        return {str(f): f.read_bytes() for f in self.tmp.rglob("*") if f.is_file()}

    # --- calls ---

    def call(self, event, cwd=None, **data):
        data.setdefault("cwd", str(cwd or self.root))
        return hooks.handle(event, data, str(cwd or self.root))

    def pre(self, tool, tid="t1", cwd=None, **tool_input):
        return self.call("PreToolUse", cwd, tool_name=tool, tool_input=tool_input, tool_use_id=tid)

    def post(self, tid="t1", event="PostToolUse", cwd=None):
        return self.call(event, cwd, tool_name="Bash", tool_input={}, tool_use_id=tid)

    def edit(self, path, old="class", new="struct", **more):
        return self.pre("Edit", file_path=str(path), old_string=old, new_string=new, **more)

    def write(self, path, content="x\n", **more):
        return self.pre("Write", file_path=str(path), content=content, **more)

    def prompt(self, text):
        return self.call("UserPromptSubmit", prompt=text)

    def denied(self, answer, *parts):
        self.assertIsNotNone(answer, "allowed")
        self.assertEqual(list(answer), ["hookSpecificOutput"])
        out = answer["hookSpecificOutput"]
        self.assertEqual((out["hookEventName"], out["permissionDecision"]), ("PreToolUse", "deny"))
        for part in parts:
            self.assertIn(part, out["permissionDecisionReason"])
        return out["permissionDecisionReason"]

    def allowed(self, answer):
        self.assertIsNone(answer)

    def reported(self, answer, *names):
        self.assertIsNotNone(answer, "not reported")
        shown = ", ".join(names)
        self.assertEqual(answer, {
            "systemMessage": texts.files_changed_owner([*names]),
            "decision": "block",
            "reason": "Owner or workflow files changed while this tool ran: %s. Ask the owner whether it was them "
                      "before you do anything else." % shown})
        self.assertIn(shown, answer["systemMessage"])
        self.assertIn("If that was you, carry on", answer["systemMessage"])


EVENTS = ("SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "PostToolUseFailure", "Stop")


class SilentTests(Base):
    def test_no_project_is_silent_and_writes_nothing(self):
        (self.tmp / "plain").mkdir()
        before = self.files()
        data = {"prompt": "/guided-learning:finish-phase 2", "tool_name": "Edit", "tool_use_id": "t1",
                "tool_input": {"file_path": str(self.tmp / "plain" / "a.cs"), "old_string": "a", "new_string": "b"},
                "last_assistant_message": "x"}
        bad_path = dict(data, tool_input={"file_path": "a\0b"})
        no_path = dict(data, tool_input={})
        for event in EVENTS + ("Nonsense",):
            for d in (data, bad_path, no_path, {}, None, [], "x"):
                self.assertIsNone(hooks.handle(event, d, str(self.tmp / "plain")), (event, d))
        self.assertEqual(self.files(), before)

    def test_unknown_event_answers_nothing(self):
        self.make()
        (self.root / ".claude" / "learning" / "project.json").write_bytes(b"{")
        self.assertIsNone(self.call("Nonsense"))

    def test_project_found_from_a_subfolder(self):
        self.make()
        self.denied(self.edit("Moth.cs", cwd=self.root / "src"), "src/Moth.cs")


class SessionStartTests(Base):
    def test_session_start_line(self):
        found = self.make()
        line = render.one_line(found)
        self.assertEqual(self.call("SessionStart"), {
            "systemMessage": line,
            "hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": line}})
        self.assertTrue(line.startswith("Learning hooks: on"))

    def test_session_start_line_in_rehearsal(self):
        self.make()
        self.rehearse()
        self.assertIn("REHEARSAL", self.call("SessionStart")["systemMessage"])


class PromptTests(Base):
    CODE = dict({"src/%s.cs" % n: shell([]) for n in ("Moth", "Lamp", "Keeper")}, **TEST_CODE)
    PASSED = {t: "passed" for s in full_plan()["scripts"] for t in s["tests"]}
    LOG = [{"kind": "measure", "target": "wins", "value": 50}, {"kind": "rating", "concept": "ai", "rating": "with help"}]

    def ready(self):
        found = self.make({"branch": "stage-2", "log": self.LOG, "results": {"Unit": suite_result(self.PASSED)}},
                          files=self.CODE)
        helpers.write_json(found.state_path(2), dict(self.data(), planHash=store.file_hash(found.plan_path(2))))
        return found

    def test_start_phase_blocked(self):
        found = self.make(n=1)
        before = self.files()
        expected = commands.run(found, "start", "2")
        self.assertFalse(expected.ok)
        for text in ("/start-phase 2", "  /guided-learning:start-phase   phase-2 "):
            self.assertEqual(self.prompt(text), {"decision": "block", "reason": expected.text})
        self.assertEqual(self.files(), before)

    def test_success_adds_the_text_as_context(self):
        found = self.make()
        out = self.prompt("/guided-learning:summarize-phase 2")
        self.assertEqual(out, {"hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit", "additionalContext": commands.run(found, "summarize", "2").text}})

    def test_other_prompts_answer_nothing(self):
        self.make()
        for text in ("hello", "/clear", "please /finish-phase 2", "/setup-learning", "/guided-learning:setup-learning"):
            self.assertIsNone(self.prompt(text), text)

    def test_finish_writes_done_only_from_the_prompt(self):
        found = self.ready()
        self.pre("Bash", command="/finish-phase 2")
        self.call("Stop", last_assistant_message="/finish-phase 2")
        self.assertEqual(self.data()["status"], "build")
        out = self.prompt("/finish-phase 2")
        self.assertEqual(out["hookSpecificOutput"]["additionalContext"], commands.closing_text(found, 2))
        self.assertEqual((self.data()["status"], self.data()["closing"]), ("done", {"pending": True, "tries": 0}))

    def test_learning_py_has_no_owner_command(self):
        import learning
        for name in ("start", "approve", "build", "finish"):
            self.assertNotIn(name, learning.SUBCOMMANDS)
            self.assertNotIn(name + "-phase", learning.SUBCOMMANDS)

    def test_rehearsal_works_on_the_fake_project(self):
        self.make(n=1)
        fake = self.rehearse({"status": "done", "locked": None})
        self.prompt("/start-phase 3")
        self.assertEqual(self.data(3, fake)["status"], "planning")
        self.assertFalse((self.root / "Docs" / "learning" / "phase-3.json").exists())


class LockedTests(Base):
    def spellings(self):
        path = str(self.root / "src" / "Moth.cs")
        found = {"plain": path,
                 "relative": os.path.join("src", "Moth.cs"),
                 "dots": os.path.join(str(self.root), "Docs", "..", "src", ".", "Moth.cs"),
                 "forward slashes": path.replace(os.sep, "/"),
                 "spaces around": "  " + path + " "}
        if os.name == "nt":
            found.update({"case": path.upper(), "long path": "\\\\?\\" + path, "device path": "\\\\.\\" + path,
                          "stream": path + "::$DATA", "trailing dot": path + ".", "trailing space": path + " ",
                          "bash drive": "/" + path[0].lower() + path[2:].replace("\\", "/"),
                          "cygwin drive": "/cygdrive/" + path[0].lower() + path[2:].replace("\\", "/")})
        return found

    def test_locked_script_refused(self):
        self.make()
        for name, path in self.spellings().items():
            for tool, rest in (("Edit", {"old_string": "class", "new_string": "struct"}),
                               ("Write", {"content": MOTH + "x"}),
                               ("MultiEdit", {"edits": [{"old_string": "class", "new_string": "struct"}]})):
                with self.subTest(spelling=name, tool=tool):
                    self.denied(self.pre(tool, file_path=path, **rest), "src/Moth.cs is locked", "hint")
        self.denied(self.pre("NotebookEdit", notebook_path=str(self.root / "src" / "Moth.cs"), new_source="x"),
                    "src/Moth.cs is locked")
        self.assertFalse((self.root / ".claude" / "learning" / "local").exists(), "a refused edit has no snapshot")

    def test_locked_script_refused_through_the_home_folder(self):
        self.make()
        with mock.patch.dict(os.environ, {"HOME": str(self.tmp), "USERPROFILE": str(self.tmp)}):
            self.denied(self.edit("~/game/src/Moth.cs"), "src/Moth.cs is locked")

    def test_locked_script_refused_through_a_link(self):
        self.make()
        link = self.tmp / "link"
        try:
            if os.name == "nt":
                import _winapi
                _winapi.CreateJunction(str(self.root / "src"), str(link))
            else:
                os.symlink(str(self.root / "src"), str(link))
        except (OSError, ImportError, AttributeError):
            self.skipTest("no links here")
        self.denied(self.edit(link / "Moth.cs"), "src/Moth.cs is locked")
        self.denied(self.edit(link / "Moth.cs", cwd=self.tmp), "src/Moth.cs is locked")

    def test_locked_path_in_the_state_may_be_spelled_differently(self):
        self.make({"locked": ["src/../src/Moth.cs"]})
        self.denied(self.edit("src/Moth.cs"), "locked")

    def test_locked_script_that_is_gone_stays_locked(self):
        self.make(files={})
        self.denied(self.write("src/Moth.cs"), "locked")

    def test_unlocked_file_allowed(self):
        self.make()
        for path in ("src/Other.cs", "src/New.cs", "README.md", "Docs/learning/phase-2.md",
                     str(self.tmp / "elsewhere.cs")):
            self.allowed(self.write(path))
        self.allowed(self.pre("Read", file_path=str(self.root / "src" / "Moth.cs")))
        self.allowed(self.pre("Bash", command="ls"))

    def test_done_and_skipped_phases_do_not_lock(self):
        for status in ("done", "skipped"):
            self.make({"status": status}, files={"src/Moth.cs": "class Moth {}\n"})
            self.allowed(self.edit("src/Moth.cs"))

    def test_second_locked_phase_counts(self):
        self.make({"status": "done", "locked": []}, n=1)
        self.make(n=2)
        self.denied(self.edit("src/Moth.cs"), "phase 2")

    def test_locked_script_of_a_phase_on_another_branch(self):
        self.make({"locked": []})
        if not helpers.git_init(self.root):
            self.skipTest("git is not available")
        helpers.git(self.root, "branch", "stage-3")
        record = self.root / ".claude" / "learning" / "local" / "open.json"
        helpers.write_json(record, {"3": {"branch": "stage-3", "locked": ["src/Other.cs"], "built": True}})
        text = self.denied(self.edit(self.root / "src" / ".." / "src" / "Other.cs"), "src/Other.cs is locked", "stage-3")
        self.assertIn("phase 3", text)
        self.allowed(self.edit("src/Free.cs", tid="t2"))
        with mock.patch.object(state, "current_branch", return_value="stage-3"):
            self.allowed(self.edit("src/Other.cs", tid="t3"))   # here the phase file itself decides
        helpers.write_json(self.root / "Docs" / "learning" / "phase-3.json", {"status": "done"})
        self.allowed(self.edit("src/Other.cs", tid="t4"))
        (self.root / "Docs" / "learning" / "phase-3.json").unlink()
        helpers.git(self.root, "branch", "-D", "stage-3")
        self.allowed(self.edit("src/Other.cs", tid="t5"))

    def test_a_phase_that_is_done_on_another_branch_refuses_no_edit(self):
        self.make({"locked": []})
        if not helpers.git_init(self.root):
            self.skipTest("git is not available")
        helpers.git(self.root, "switch", "-q", "-c", "stage-3")
        helpers.commit(self.root)
        helpers.git(self.root, "switch", "-q", "main")
        helpers.write_json(self.root / ".claude" / "learning" / "local" / "open.json",
                           {"3": {"branch": "stage-3", "done": True, "locked": ["src/Other.cs"]}})
        self.allowed(self.edit("src/Other.cs"))
        self.allowed(self.write("src/New.cs", tid="t2"))

    def test_the_local_record_is_guarded_and_not_reported(self):
        self.make()
        record = self.root / ".claude" / "learning" / "local" / "open.json"
        self.denied(self.write(record, "{}"), "learning script")
        self.pre("Bash")
        helpers.write_json(record, {"2": {"branch": "stage-2", "locked": [], "built": True}})
        self.assertIsNone(self.post())

    def test_edit_from_a_chat_opened_elsewhere_is_guarded(self):
        self.make()
        (self.tmp / "plain").mkdir()
        before = self.files()
        for cwd in (self.tmp / "plain", self.tmp):
            self.denied(self.edit(self.root / "src" / "Moth.cs", cwd=cwd), "locked")
            self.denied(self.write(self.root / ".claude" / "learning" / "config.json", cwd=cwd))
            self.allowed(self.edit(self.root / "src" / "Other.cs", cwd=cwd))
        self.assertEqual(self.files(), before, "no snapshot outside of the project")

    def test_unreadable_project_of_the_edited_file_denies(self):
        self.make()
        (self.tmp / "plain").mkdir()
        real = store.read

        def read(path):
            if Path(path).name == "project.json":
                raise PermissionError(13, "Permission denied", str(path))
            return real(path)

        with mock.patch.object(store, "read", read):
            self.denied(self.edit(self.root / "src" / "Moth.cs", cwd=self.tmp / "plain"),
                        "guided-learning error: ", "project.json")

    def test_edit_of_another_game_is_guarded(self):
        self.make({"locked": []})
        other = self.tmp / "other"
        self.make({"locked": ["src/Lamp.cs"]}, files={"src/Lamp.cs": MOTH}, root=other)
        self.denied(self.edit(other / "src" / "Lamp.cs"), "src/Lamp.cs is locked")
        self.assertFalse((other / ".claude" / "learning" / "local").exists())

    def test_edit_without_a_path_is_denied(self):
        self.make()
        for tool_input in ({}, {"file_path": ""}, {"file_path": 5}):
            self.denied(self.pre("Edit", **tool_input), "guided-learning error: ")


class TodoTests(Base):
    def setUp(self):
        super().setUp()
        self.make({"turn": "ai", "locked": []})

    LINE = "    // TODO(owner 1.1) do something\n"

    def test_todo_removal_refused_before_the_lock(self):
        for tool, rest in (
                ("Edit", {"old_string": self.LINE, "new_string": "    Turn();\n"}),
                ("Write", {"content": shell(["1.2"])}),
                ("MultiEdit", {"edits": [{"old_string": "class", "new_string": "struct"},
                                         {"old_string": "owner 1.1", "new_string": "owner 1.3"}]})):
            with self.subTest(tool=tool):
                text = self.denied(self.pre(tool, file_path="src/Moth.cs", **rest), "TODO(owner 1.1)", "src/Moth.cs")
                self.assertNotIn("1.2", text)

    def test_edits_that_keep_the_todos_are_allowed(self):
        self.allowed(self.edit("src/Moth.cs"))
        self.allowed(self.edit("src/Moth.cs", "do something", "hint: turn around", replace_all=True))
        self.allowed(self.write("src/Moth.cs", shell(["1.2", "1.1", "1.3"])))
        self.allowed(self.pre("MultiEdit", file_path="src/Moth.cs", edits=[
            {"old_string": self.LINE, "new_string": ""}, {"old_string": "class Shell {\n", "new_string": "X {\n" + self.LINE}]))
        self.allowed(self.write("src/New.cs", "class New {}\n"))

    def test_line_endings_do_not_matter(self):
        path = self.root / "src" / "Moth.cs"
        path.write_bytes(b"\xef\xbb\xbf" + MOTH.replace("\n", "\r\n").encode("utf-8"))
        self.denied(self.edit(path, self.LINE + "    // TODO(owner 1.2)", "x"), "1.1), TODO(owner 1.2)")
        self.denied(self.edit(path, (self.LINE + "    // TODO(owner 1.2)").replace("\n", "\r\n"), "x"), "1.1")

    def test_text_that_is_not_there_is_left_to_the_tool(self):
        self.allowed(self.edit("src/Moth.cs", "no such text TODO(owner 1.1)", ""))
        self.allowed(self.pre("MultiEdit", file_path="src/Moth.cs", edits=[
            {"old_string": self.LINE, "new_string": ""}, {"old_string": "no such text", "new_string": ""}]))
        self.allowed(self.edit("src/Moth.cs", "", "x"))

    def test_replace_all_and_the_first_one_only(self):
        (self.root / "src" / "Moth.cs").write_bytes(("// A TODO(owner 1.1)\n// A TODO(owner 1.1)\n").encode())
        self.allowed(self.edit("src/Moth.cs", "// A TODO(owner 1.1)\n", ""))
        self.denied(self.edit("src/Moth.cs", "// A TODO(owner 1.1)\n", "", replace_all=True), "1.1")

    def test_edits_count_only_for_multiedit(self):
        for edits in ([], [{"old_string": "class", "new_string": "struct"}]):
            self.denied(self.edit("src/Moth.cs", self.LINE, "", edits=edits), "1.1")
        self.denied(self.pre("MultiEdit", file_path="src/Moth.cs", old_string="class", new_string="struct",
                             edits=[{"old_string": self.LINE, "new_string": ""}]), "1.1")

    def test_planned_script_outside_the_code_folders(self):
        plan = full_plan()
        plan["scripts"][0]["path"] = "Tools/Moth.py"
        self.make({"turn": "ai", "locked": []}, plan=plan, files={"Tools/Moth.py": MOTH, "Tools/Free.py": MOTH})
        self.denied(self.write("Tools/Moth.py"), "1.1")
        self.allowed(self.write("Tools/Free.py"))

    def test_broken_plan_can_still_be_mended(self):
        plan = self.root / "Docs" / "learning" / "phase-3.plan.json"
        for text in ('{"todos": ["TODO(owner 1.1)"],', '{"scripts": 5}', '{"scripts": [1, {"path": 4}]}'):
            plan.write_bytes(text.encode())
            helpers.write_json(self.root / "Docs" / "learning" / "phase-3.json", {"status": "planning"})
            self.allowed(self.write(plan, "{}"))

    def test_notebook_cell(self):
        path = self.root / "src" / "Moth.ipynb"
        cells = [{"id": "a", "cell_type": "code", "source": ["# TODO(owner 1.1) x\n", "pass"]},
                 {"cell_type": "code", "source": "# TODO(owner 1.2) x"}]
        helpers.write_json(path, {"cells": cells})

        def cell(**kw):
            return self.pre("NotebookEdit", notebook_path=str(path), **kw)

        self.denied(cell(cell_id="a", new_source="done"), "1.1")
        self.denied(cell(cell_id="cell-1", new_source="done"), "1.2")
        self.denied(cell(cell_id="a", new_source="", edit_mode="delete"), "1.1")
        self.allowed(cell(cell_id="a", new_source="# TODO(owner 1.1) y"))
        self.allowed(cell(cell_id="a", new_source="new", edit_mode="insert"))
        self.allowed(cell(cell_id="zzz", new_source="new"))
        path.write_bytes(b"not a notebook TODO(owner 1.1)")
        self.allowed(cell(cell_id="a", new_source="done"))


class WorkflowFileTests(Base):
    def test_code_refused_while_planning_and_allowed_after_build_phase(self):
        found = self.make({"status": "planning", "turn": None, "part": None, "locked": None})
        self.denied(self.write("src/New.cs"), "/approve-phase 2")
        self.denied(self.edit("src/Other.cs"), "/approve-phase 2")
        for path in ("Docs/learning/phase-2.plan.json", "Docs/learning/phase-2.md", "README.md", "srcery/a.cs"):
            self.allowed(self.write(path))
        self.assertNotIn("decision", self.prompt("/approve-phase 2"))
        text = self.denied(self.write("src/New.cs"), "/build-phase 2")
        self.assertNotIn("/approve-phase", text)
        self.assertNotIn("decision", self.prompt("/build-phase 2"))
        self.allowed(self.write("src/New.cs"))
        self.assertEqual(found.phase_numbers(), [2])

    def test_code_dir_that_holds_everything_still_lets_the_plan_be_written(self):
        self.make({"status": "planning", "locked": None}, settings={"code": ["."]})
        for path in ("Docs/learning/phase-2.plan.json", "Docs/learning/phase-2.md"):
            self.allowed(self.write(path))
        self.denied(self.write("src/New.cs"), "/approve-phase 2")

    def test_done_and_skipped_phases_leave_the_code_open(self):
        for status in ("done", "skipped"):
            self.make({"status": status, "turn": None, "locked": None})
            self.allowed(self.write("src/New.cs"))

    def test_planning_next_to_a_done_phase(self):
        self.make({"status": "done", "locked": []}, n=1)
        self.make({"status": "planning", "turn": None, "locked": None}, n=2)
        self.denied(self.write("src/New.cs"), "/approve-phase 2")

    def test_phase_files(self):
        docs = "Docs/learning/"
        self.make({"planHash": "abc"})
        helpers.write_json(self.root / docs / "phase-1.json", {"status": "done"})
        helpers.write_json(self.root / docs / "phase-3.json", {"status": "planning"})
        for n in (1, 2, 3, 4):
            self.denied(self.write(docs + "phase-%d.json" % n), "learning.py log")
        self.denied(self.edit(docs + "phase-2.plan.json", "Moth", "Bat"), "/approve-phase 2 change:")
        self.allowed(self.write(docs + "phase-3.plan.json"))
        self.allowed(self.write(docs + "phase-4.plan.json"))
        self.make({"status": "build", "planHash": None})
        self.denied(self.write(docs + "phase-2.plan.json"), "/approve-phase 2 change:")

    def test_config_json_refused(self):
        self.make()
        for path in (".claude/learning/config.json", ".claude/learning/project.json",
                     ".claude/learning/local/seen.json", ".claude/learning/local/written/phase-2.json",
                     ".claude/learning/local/new/a.txt"):
            self.denied(self.write(path, "{}"), path)
        self.allowed(self.write(".claude/learning/notes.md"))
        self.allowed(self.write(".claude/settings.json"))

    def test_real_files_guarded_in_rehearsal(self):
        self.make()
        fake = self.rehearse()
        self.denied(self.edit("src/Moth.cs"), "src/Moth.cs is locked")
        self.denied(self.write("Docs/learning/phase-2.json"))
        self.denied(self.write(".claude/learning/config.json"))
        self.denied(self.edit(fake / "src" / "Fake.cs"), "src/Fake.cs is locked")
        self.denied(self.write(fake / "Docs/learning/phase-2.json"))
        self.denied(self.write(fake / ".claude/learning/project.json"))
        self.denied(self.edit(fake / "src" / "Fake.cs", cwd=fake / "src"), "locked")
        self.allowed(self.edit("src/Other.cs"))
        helpers.set_switch(self.root, '{"rehearsal": false}')
        self.allowed(self.edit(fake / "src" / "Fake.cs"))


class SnapshotTests(Base):
    def snapshots(self):
        folder = self.root / ".claude" / "learning" / "local" / "snapshots"
        return sorted(f.name for f in folder.iterdir()) if folder.is_dir() else []

    def append(self, rel, text="// more\n"):
        with open(self.root / rel, "ab") as f:
            f.write(text.encode())

    def test_shell_change_is_reported(self):
        self.make({"planHash": "x"})
        for rel in ("src/Moth.cs", "Docs/learning/phase-2.json", "Docs/learning/phase-2.plan.json",
                    ".claude/learning/project.json"):
            with self.subTest(rel):
                self.allowed(self.pre("Bash", command="echo"))
                self.append(rel, " \n")
                after = (self.root / rel).read_bytes()
                self.reported(self.post(), rel)
                self.assertEqual((self.root / rel).read_bytes(), after, "nothing is reverted")
                self.assertIsNone(self.post(), "reported once")
                self.assertEqual(self.snapshots(), [])

    def test_appeared_and_gone(self):
        self.make()
        self.pre("Bash")
        helpers.set_switch(self.root, '{"rehearsal": false}')
        helpers.write_json(self.root / "Docs" / "learning" / "phase-3.json", {"status": "build", "turn": "ai"})
        (self.root / "src" / "Moth.cs").unlink()
        self.reported(self.post(), ".claude/learning/config.json", "Docs/learning/phase-3.json", "src/Moth.cs")
        self.pre("Bash")
        (self.root / "Docs" / "learning" / "phase-3.json").unlink()
        self.reported(self.post(), "Docs/learning/phase-3.json")

    def test_project_json_that_is_gone_is_reported(self):
        self.make()
        self.pre("Bash")
        (self.root / ".claude" / "learning" / "project.json").unlink()
        self.reported(self.post(), ".claude/learning/project.json")
        self.assertIsNone(self.post())

    def test_switching_rehearsal_on_reports_only_the_switch(self):
        self.make()
        self.rehearse()
        helpers.set_switch(self.root, '{"rehearsal": false}')
        self.pre("Bash")
        helpers.set_switch(self.root, '{"rehearsal": true}')
        self.reported(self.post(), ".claude/learning/config.json")

    def test_phase_file_broken_by_the_tool_is_reported(self):
        self.make()
        self.pre("Bash")
        (self.root / "Docs" / "learning" / "phase-2.json").write_bytes(b'{"status": ')
        self.reported(self.post(), "Docs/learning/phase-2.json")

    def test_project_json_with_wrong_types_does_not_lose_the_report(self):
        for text in (b'{"docs": 5, "code": 5}', b'{"docs": ["x"]}'):
            self.make()
            self.pre("Bash")
            self.append("src/Moth.cs")
            (self.root / ".claude" / "learning" / "project.json").write_bytes(text)
            self.reported(self.post(), ".claude/learning/project.json", "src/Moth.cs")

    def test_broken_project_json_does_not_lose_the_report(self):
        self.make()
        self.pre("Bash")
        self.append("src/Moth.cs")
        (self.root / ".claude" / "learning" / "project.json").write_bytes(b"{")
        self.reported(self.post(), ".claude/learning/project.json", "src/Moth.cs")
        self.assertIn("guided-learning error: ", self.post()["systemMessage"])

    def test_failed_tool_is_reported_in_its_own_form(self):
        self.make()
        self.pre("Bash")
        self.append("src/Moth.cs")
        self.assertEqual(self.post(event="PostToolUseFailure"), {
            "systemMessage": texts.files_changed_owner(["src/Moth.cs"]),
            "hookSpecificOutput": {"hookEventName": "PostToolUseFailure",
                                   "additionalContext": texts.files_changed_ai(["src/Moth.cs"])}})

    def test_unchanged_unwatched_and_line_endings_are_not_reported(self):
        self.make()
        self.pre("Bash")
        self.append("src/Other.cs")
        self.append("Docs/learning/phase-2.md")
        self.append("README.md")
        path = self.root / "src" / "Moth.cs"
        path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
        self.assertIsNone(self.post())

    def test_change_by_learning_py_is_not_reported(self):
        found = self.make(files=dict({"src/Moth.cs": MOTH, "src/Lamp.cs": shell(["2.1"]),
                                      "src/Keeper.cs": shell(["3.1"])}, **TEST_CODE),
                          stored={"turn": "ai", "locked": [], "branch": "stage-2"})
        out = self.tmp / "out.csv"
        tests = [t for s in full_plan()["scripts"] for t in s["tests"]]
        out.write_bytes("".join("%s,fail\n" % t for t in tests).encode())
        os.utime(str(out), (helpers.FRESH, helpers.FRESH))
        for act in (lambda: log.add(found, 2, "help", script=1, level=2),
                    lambda: results.record(found, 2, "Unit", str(out)),
                    lambda: self.assertTrue(commands.hand_over(found, 2).ok, commands.hand_over(found, 2).text),
                    lambda: (log.add(found, 2, "note", text="a"), log.add(found, 2, "note", text="b"))):
            self.pre("Bash")
            before = self.data()
            act()
            self.assertNotEqual(self.data(), before)
            self.assertIsNone(self.post())

    def test_change_by_an_owner_command_is_not_reported(self):
        self.make({"status": "done", "locked": [], "branch": None}, n=1)
        self.pre("Bash")
        self.assertNotIn("decision", self.prompt("/start-phase 2"))
        self.assertIsNone(self.post())

    def test_change_after_learning_py_is_reported(self):
        found = self.make()
        self.pre("Bash")
        log.add(found, 2, "note", text="a")
        self.append("Docs/learning/phase-2.json", "\n")
        self.reported(self.post(), "Docs/learning/phase-2.json")

    def test_note_that_cannot_be_written_does_not_undo_the_record(self):
        found = self.make()
        (self.root / ".claude" / "learning" / "local").write_bytes(b"a file, not a folder")
        log.add(found, 2, "note", text="a")
        self.assertEqual(self.data()["log"][-1]["text"], "a")

    def test_note_is_written_while_the_lock_is_held(self):
        found = self.make()
        seen = []
        real = store.write

        def spy(path, data):
            seen.append((Path(path).parent.name, Path(str(found.state_path(2)) + ".lock").exists()))
            real(path, data)

        with mock.patch.object(store, "write", spy):
            log.add(found, 2, "note", text="a")
        self.assertEqual(seen, [("learning", True), ("written", True)])

    def test_note_that_is_a_moment_late_is_waited_for(self):
        found = self.make()
        self.pre("Bash")
        real = store.write

        def slow(path, data):
            if Path(path).parent.name == "written":
                time.sleep(0.3)
            real(path, data)

        with mock.patch.object(store, "write", slow):
            t = threading.Thread(target=lambda: log.add(found, 2, "note", text="a"))
            t.start()
            while not self.data().get("log"):
                time.sleep(0.005)
            answer = self.post()
            t.join()
        self.assertIsNone(answer)

    def test_script_that_finishes_between_two_looks_is_not_reported(self):
        found = self.make()
        log.add(found, 2, "note", text="a")
        self.pre("Bash")
        path, lock = found.state_path(2), Path(str(found.state_path(2)) + ".lock")
        lock.write_bytes(b"x")   # another process is in update_state: the file is written, the note is not
        self.append("Docs/learning/phase-2.json", "\n")
        real, looks = hooks._noted, []

        def noted(note):
            value = real(note)
            looks.append(value)
            if len(looks) == 2:   # it finishes right after the note was read
                store.write(found.note_path(2), {"hash": store.file_hash(path)})
                lock.unlink()
            return value

        with mock.patch.object(hooks, "_noted", noted):
            self.assertIsNone(self.post())
        self.assertEqual(len(looks), 3)

    def test_every_state_write_is_noted(self):
        for f in (ROOT / "scripts").rglob("*.py"):
            if f.name not in ("project.py", "store.py"):
                self.assertNotIn("store.update(", f.read_text(encoding="utf-8"), f.name)

    def test_owner_saves_while_a_long_tool_call_runs(self):
        self.make()
        self.allowed(self.pre("Bash", tid="long"))
        mine = MOTH.replace("// TODO(owner 1.1) do something", "Turn();")
        (self.root / "src" / "Moth.cs").write_bytes(mine.encode())
        answer = self.post("long")
        self.reported(answer, "src/Moth.cs")
        self.assertNotIn("not allowed", json.dumps(answer))
        self.assertEqual((self.root / "src" / "Moth.cs").read_bytes(), mine.encode())
        self.allowed(self.pre("Bash", tid="next"))
        self.assertIsNone(self.post("next"))
        self.assertIsNone(self.prompt("that was me"))

    def test_two_snapshots_in_flight(self):
        self.make()
        self.pre("Bash", tid="a")
        self.append("src/Moth.cs")
        self.pre("Task", tid="b")
        self.assertEqual(self.snapshots(), ["a.json", "b.json"])
        self.assertIsNone(self.post("b"), "b began after the change")
        self.reported(self.post("a"), "src/Moth.cs")
        self.assertEqual(self.snapshots(), [])

    def test_both_projects_are_watched_in_rehearsal(self):
        self.make()
        fake = self.rehearse()
        self.pre("Bash")
        self.append("src/Moth.cs")
        with open(fake / "src" / "Fake.cs", "ab") as f:
            f.write(b"x")
        log.add(project.find(self.root), 2, "note", text="by the script")
        self.reported(self.post(), ".claude/learning/rehearsal/src/Fake.cs", "src/Moth.cs")

    def test_snapshot_names_are_safe(self):
        self.make()
        for tid in ("../../evil", "a/b", "a_b", "x" * 300, "con\0"):
            self.pre("Bash", tid=tid)
        self.assertEqual(len(self.snapshots()), 5)
        self.append("src/Moth.cs")
        self.reported(self.post("../../evil"), "src/Moth.cs")

    def test_no_tool_use_id_no_snapshot(self):
        self.make()
        for tid in (None, "", 5):
            self.allowed(self.pre("Bash", tid=tid))
            self.assertIsNone(self.post(tid))
        self.assertEqual(self.snapshots(), [])

    def test_old_snapshots_are_deleted(self):
        self.make()
        self.pre("Bash", tid="old")
        self.pre("Bash", tid="young")
        path = self.root / ".claude" / "learning" / "local" / "snapshots" / "old.json"
        long_ago = time.time() - 25 * 3600
        os.utime(str(path), (long_ago, long_ago))
        self.pre("Bash", tid="now")
        self.assertEqual(self.snapshots(), ["now.json", "young.json"])

    def test_hand_over_during_a_call_reports_nothing(self):
        found = self.make({"turn": "ai", "locked": []})
        self.pre("Bash")
        found.update_state(2, lambda d: d.update(locked=["src/Moth.cs"], turn="owner"))
        self.assertIsNone(self.post())

    def test_refused_edit_after_a_snapshot_changes_nothing(self):
        self.make()
        self.pre("Bash", tid="a")
        self.denied(self.edit("src/Moth.cs", tid="b"))
        self.assertEqual(self.snapshots(), ["a.json"])


class ErrorTests(Base):
    def breaks(self):
        """The ways to make a hook raise, each with a word of the message."""
        pj = self.root / ".claude" / "learning" / "project.json"
        yield lambda: pj.write_bytes(b'{"docs": "x",\n}'), "project.json"
        yield lambda: pj.write_bytes(b"\xff\xfe"), "project.json"
        yield lambda: pj.write_bytes(b"[]"), "project.json"
        yield lambda: helpers.write_json(pj, dict(helpers.PROJECT_JSON, code="src")), '"code"'
        yield lambda: helpers.write_json(pj, {}), '"docs"'

    def test_exception_denies(self):
        for break_, word in self.breaks():
            self.make()
            break_()
            for tool in ("Edit", "Bash", "Read"):
                self.denied(self.pre(tool, file_path="src/Other.cs"), "guided-learning error: ", word)
            out = self.prompt("/summarize-phase 2")
            self.assertEqual(list(out), ["decision", "reason"])
            self.assertEqual(out["decision"], "block")
            self.assertTrue(out["reason"].startswith("guided-learning error: "), out)

    def test_exception_in_stop_does_not_block(self):
        for break_, word in self.breaks():
            self.make()
            break_()
            for event in ("Stop", "SessionStart", "PostToolUse", "PostToolUseFailure"):
                out = self.call(event, tool_use_id="t1")
                self.assertEqual(list(out), ["systemMessage"], event)
                self.assertTrue(out["systemMessage"].startswith("guided-learning error: "), out)
                self.assertIn(word, out["systemMessage"])

    def test_broken_phase_file(self):
        self.make()
        (self.root / "Docs" / "learning" / "phase-2.json").write_bytes(b'{"status": "build",\n"x"}')
        self.denied(self.edit("src/Other.cs"), "guided-learning error: ", "phase-2.json", "line 2")
        self.denied(self.pre("Bash"), "guided-learning error: ")
        self.assertEqual(list(self.call("Stop", last_assistant_message="x")), ["systemMessage"])
        self.assertEqual(self.prompt("/summarize-phase 2")["decision"], "block")
        self.assertIsNone(self.prompt("hello"))

    def test_odd_state_values_do_not_open_the_guard(self):
        self.make({"locked": ["src/Moth.cs", 5, None, {}]})
        self.denied(self.edit("src/Moth.cs"), "locked")
        self.make({"locked": "src/Moth.cs"})
        self.allowed(self.edit("src/Other.cs"))
        self.make({"closing": 5})
        self.assertIsNone(self.call("Stop", last_assistant_message="x"))

    def test_broken_snapshot_is_a_message(self):
        self.make()
        for text in (b"{", b"{}", b'{"files": 5}', b'{"files": {"src/Moth.cs": 5}}'):
            self.pre("Bash")
            path = self.root / ".claude" / "learning" / "local" / "snapshots" / "t1.json"
            path.write_bytes(text)
            out = self.post()
            self.assertEqual(list(out), ["systemMessage"], text)
            self.assertIn("guided-learning error: ", out["systemMessage"])

    def test_unforeseen_exception(self):
        self.make()
        with mock.patch.object(store, "read", side_effect=RuntimeError("boom")):
            self.denied(self.pre("Bash"), "guided-learning error: ", "boom")
            self.assertIn("boom", self.prompt("/summarize-phase")["reason"])
            self.assertIn("boom", self.call("Stop")["systemMessage"])

    def test_input_that_is_no_object(self):
        self.make()
        for data in (None, [], "x"):
            self.denied(hooks.handle("PreToolUse", data, str(self.root)), "guided-learning error: ")
            self.assertEqual(hooks.handle("UserPromptSubmit", data, str(self.root))["decision"], "block")
            self.assertEqual(list(hooks.handle("Stop", data, str(self.root))), ["systemMessage"])

    def test_tool_input_that_is_no_object(self):
        self.make()
        self.denied(self.call("PreToolUse", tool_name="Edit", tool_input=5, tool_use_id="t1"), "guided-learning error: ")


class StopTests(Base):
    def setUp(self):
        super().setUp()
        self.project = self.make({"status": "done", "branch": "stage-2", "locked": [],
                                  "closing": {"pending": True, "tries": 0}})
        self.text = commands.closing_text(self.project, 2)

    def stop(self, message=None):
        return self.call("Stop", last_assistant_message=message)

    def closing(self):
        return self.data()["closing"]

    def asked(self, answer):
        self.assertEqual(answer["decision"], "block")
        self.assertTrue(answer["reason"].endswith("\n" + self.text), answer)
        self.assertNotIn("systemMessage", answer)

    def test_stop_asks_until_present(self):
        self.asked(self.stop("All done."))
        self.asked(self.stop(None))
        self.assertEqual(self.closing(), {"pending": True, "tries": 2})
        self.assertIsNone(self.stop("Well done!\n\n" + self.text))
        self.assertFalse(self.closing()["pending"])
        self.assertIsNone(self.stop("All done."))

    def test_fences_spaces_and_line_endings_are_fine(self):
        lines = self.text.split("\n")
        for message in ("```\n" + self.text + "\n```", "\r\n".join(lines), "\n".join("  " + x + "  " for x in lines),
                        self.text + "\n\nGood luck!", "\n\n".join(lines)):
            self.project.update_state(2, lambda d: d.update(closing={"pending": True, "tries": 0}))
            self.assertIsNone(self.stop(message), message)
            self.assertFalse(self.closing()["pending"])

    def test_a_part_of_the_text_is_not_enough(self):
        lines = self.text.split("\n")
        self.asked(self.stop("\n".join(lines[:-1])))
        self.asked(self.stop(self.text.replace("Phase 2 is done", "Phase 2 is finished")))
        self.asked(self.stop("\n".join(lines[:1] + ["something else"] + lines[1:])))

    def test_stop_gives_up_after_three(self):
        for tries in (1, 2, 3):
            self.asked(self.stop("no"))
            self.assertEqual(self.closing(), {"pending": True, "tries": tries})
        self.assertEqual(self.stop("no"), {"systemMessage": self.text})
        self.assertFalse(self.closing()["pending"])
        self.assertIsNone(self.stop("no"))

    def test_stop_without_a_closing_text_answers_nothing(self):
        self.make({"closing": None})
        before = self.files()
        self.assertIsNone(self.stop("x"))
        self.assertEqual(self.files(), before)

    def test_stop_writes_through_the_state_write(self):
        self.pre("Bash")
        self.asked(self.stop("no"))
        self.assertIsNone(self.post())

    def test_stop_in_rehearsal_looks_at_the_fake_project(self):
        fake = self.rehearse({"status": "done", "locked": [], "closing": {"pending": True, "tries": 0}})
        self.assertEqual(self.stop("no")["decision"], "block")
        self.assertEqual(self.data(2, fake)["closing"]["tries"], 1)
        self.assertEqual(self.closing()["tries"], 0)

    def test_odd_tries_count_as_none(self):
        self.project.update_state(2, lambda d: d.update(closing={"pending": True, "tries": "x"}))
        self.asked(self.stop("no"))
        self.assertEqual(self.closing()["tries"], 1)


class AnswerTests(Base):
    """hooks.answer: the bytes of stdin in, the text of stdout out."""

    def answer(self, event, raw, env=None, cwd=None):
        with mock.patch.dict(os.environ, env or {}):
            if not env:
                os.environ.pop("CLAUDE_PROJECT_DIR", None)
            with mock.patch.object(os, "getcwd", return_value=str(cwd or self.tmp)):
                return hooks.answer(event, raw)

    def test_bom_and_one_line(self):
        self.make()
        raw = b"\xef\xbb\xbf" + json.dumps({"cwd": str(self.root), "prompt": "/finish-phase x\né"}).encode()
        out = self.answer("UserPromptSubmit", raw)
        self.assertEqual(json.loads(out)["decision"], "block")
        self.assertNotIn("\n", out)

    def test_which_folder_counts(self):
        self.make()
        (self.tmp / "plain").mkdir()
        here, plain = str(self.root), str(self.tmp / "plain")
        raw = json.dumps({"cwd": plain}).encode()
        self.assertIn("on", self.answer("SessionStart", raw, {"CLAUDE_PROJECT_DIR": here}))
        self.assertEqual(self.answer("SessionStart", raw, cwd=here), "")
        self.assertIn("on", self.answer("SessionStart", json.dumps({"cwd": here}).encode(), cwd=plain))
        self.assertIn("on", self.answer("SessionStart", b"{}", cwd=here))
        self.assertIn("on", self.answer("SessionStart", b'{"cwd": 5}', cwd=here))

    def test_working_folder_that_is_gone(self):
        with mock.patch.dict(os.environ):
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
            with mock.patch.object(os, "getcwd", side_effect=FileNotFoundError):
                self.assertEqual(hooks.answer("PreToolUse", b"{"), "")

    def test_malformed_stdin(self):
        self.make()
        for raw in (b"", b"{", b"\xff\xff", b"[" * 100000, b"5"):
            self.assertEqual(self.answer("PreToolUse", raw), "")
            out = json.loads(self.answer("PreToolUse", raw, cwd=self.root))
            self.denied(out, "guided-learning error: ")
            self.assertEqual(list(json.loads(self.answer("Stop", raw, cwd=self.root))), ["systemMessage"])


class HooksJsonTests(unittest.TestCase):
    def test_every_event_calls_run_sh(self):
        data = json.loads((ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
        self.assertEqual(sorted(data), sorted(hooks.EVENTS))
        for event, entries in data.items():
            self.assertEqual(len(entries), 1)
            if "ToolUse" in event:
                self.assertEqual(entries[0]["matcher"], "*")
            self.assertEqual([h["command"] for h in entries[0]["hooks"]],
                             ['bash "${CLAUDE_PLUGIN_ROOT}/scripts/run.sh" hook %s' % event])


@unittest.skipUnless(BASH, "bash not available")
class EndToEndTests(Base):
    def hook(self, event, data, cwd=None, raw=None):
        env = dict(os.environ, GIT_CEILING_DIRECTORIES=str(self.tmp), PYTHONIOENCODING="cp1252")
        env.pop("CLAUDE_PROJECT_DIR", None)
        done = subprocess.run([BASH, RUN_SH, "hook", event], cwd=str(cwd or self.tmp),
                              env=env, input=raw if raw is not None else json.dumps(data).encode(),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
        self.assertEqual((done.returncode, done.stderr), (0, b""))
        return done.stdout.decode("utf-8")

    def test_silent_without_a_project(self):
        before = self.files()
        for event in EVENTS + ("Nonsense", ""):
            self.assertEqual(self.hook(event, {"cwd": str(self.tmp)}), "")
        self.assertEqual(self.hook("PreToolUse", None, raw=b"{"), "")
        self.assertEqual(self.files(), before)

    def test_wrong_settings_deny_on_the_command_line_too(self):
        self.make()
        helpers.write_json(self.root / ".claude" / "learning" / "project.json", dict(helpers.PROJECT_JSON, code="src"))
        done = subprocess.run([sys.executable, str(ROOT / "scripts" / "learning.py"), "status"], cwd=str(self.root),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL)
        self.assertEqual((done.returncode, done.stderr), (1, b""))
        self.assertIn("project.json", done.stdout.decode("utf-8"))
        self.assertIn(texts.setup_key("code", True), done.stdout.decode("utf-8"))

    def test_an_unknown_setting_blocks_nothing(self):
        self.make()
        helpers.write_json(self.root / ".claude" / "learning" / "project.json", dict(helpers.PROJECT_JSON, codes=["src"]))
        base = {"cwd": str(self.root), "tool_use_id": "toolu_1", "tool_name": "Write",
                "tool_input": {"file_path": str(self.root / "src" / "New.cs"), "content": "x"}}
        self.assertEqual(self.hook("PreToolUse", base), "")
        self.assertEqual(self.hook("PostToolUse", base), "")
        self.assertEqual(self.hook("Stop", {"cwd": str(self.root)}), "")
        out = json.loads(self.hook("UserPromptSubmit", {"cwd": str(self.root), "prompt": "/summarize-phase 2"}))
        self.assertNotIn("decision", out)
        self.assertIn(texts.unknown_setting("codes"),
                      json.loads(self.hook("SessionStart", {"cwd": str(self.root)}))["systemMessage"])
        locked = dict(base, tool_input={"file_path": str(self.root / "src" / "Moth.cs"), "content": "x"})
        self.denied(json.loads(self.hook("PreToolUse", locked)), "locked")   # still guarded
        done = subprocess.run([sys.executable, str(ROOT / "scripts" / "learning.py"), "status", "2"], cwd=str(self.root),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL)
        self.assertEqual((done.returncode, done.stderr), (0, b""))

    def test_edit_shell_and_prompt(self):
        self.make()
        base = {"cwd": str(self.root), "tool_use_id": "toolu_1", "tool_name": "Edit",
                "tool_input": {"file_path": str(self.root / "src" / "Moth.cs"), "old_string": "class", "new_string": "x"}}
        out = self.hook("PreToolUse", base)
        self.assertEqual(out.count("\n"), 1)
        self.denied(json.loads(out), "locked")
        self.assertEqual(self.hook("PreToolUse", dict(base, tool_name="Bash", tool_input={"command": "x"})), "")
        with open(self.root / "src" / "Moth.cs", "ab") as f:
            f.write(b"x")
        self.reported(json.loads(self.hook("PostToolUse", base)), "src/Moth.cs")
        blocked = json.loads(self.hook("UserPromptSubmit", {"cwd": str(self.root), "prompt": "/finish-phase 2"}))
        self.assertEqual(blocked["decision"], "block")

    def test_record_by_the_command_line_is_not_reported(self):
        self.make()
        base = {"cwd": str(self.root), "tool_use_id": "toolu_1", "tool_name": "Bash", "tool_input": {}}
        self.assertEqual(self.hook("PreToolUse", base), "")
        done = subprocess.run([BASH, RUN_SH, "log", "note", "text=a"],
                              cwd=str(self.root), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, timeout=60)
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertEqual(self.hook("PostToolUse", base), "")

    def test_malformed_stdin_in_a_project(self):
        self.make()
        self.denied(json.loads(self.hook("PreToolUse", None, cwd=self.root, raw=b"{")), "guided-learning error: ")


if __name__ == "__main__":
    unittest.main()
