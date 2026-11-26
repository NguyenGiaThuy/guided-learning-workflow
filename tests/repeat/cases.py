"""What the repeat runs try: the fake game of each case, what is typed, and the judge.

A judge looks at the files and at the stream of Claude Code, and never asks a model. A run passes only if the
AI tried (or the command was typed), the guard answered, and the files are as they should be.
"""
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import helpers
from helpers import FULL_MD, TEST_CODE, full_plan, shell, suite_result
from gl import commands, project, store, texts, version

PASSED, FAILED, NOT_RUN = "passed", "failed", "not run"
DID_NOT_TRY = "the AI did not try"
MODES = ("default", "acceptEdits", "auto")
SHELLS, EDITS = ("Bash", "PowerShell"), ("Edit", "Write", "MultiEdit", "NotebookEdit")
RUN_SH = (version.ROOT / "scripts" / "run.sh").as_posix()
STATE, NOTES = "Docs/learning/phase-2.json", "Docs/learning/phase-2.md"
MOTH, BAT, CONFIG = "src/Moth.cs", "src/Bat.cs", ".claude/learning/config.json"


SETTINGS = (CONFIG, ".claude/learning/project.json", "Docs/learning/phase-2.plan.json")   # of the owner, or locked
LOCKED = SETTINGS + ("src/Moth.cs", "src/Lamp.cs", "src/Keeper.cs")


@dataclass
class Verdict:
    outcome: str
    note: str = ""


@dataclass
class Case:
    name: str
    build: Callable          # build(root) writes the project
    prompts: list            # one per turn
    judge: Callable          # judge(Run) -> Verdict
    mode: str = "default"
    allowed: list = field(default_factory=list)   # --allowedTools
    options: list = field(default_factory=list)   # more of the command line
    extra: bool = False
    keep: tuple = ()         # files that nothing may change in this case ...
    only: tuple = None       # ... or, if given, the only files that may change

    def damage(self, run):
        """Files that are not as they must be, however the run ended."""
        if self.only is None:
            found = [n for n in run.changed if n in self.keep]
        else:
            found = [n for n in run.changed if n not in self.only]
        return found + [n + " (not valid JSON)" for n in run.changed if n not in found and run.is_broken(n)]


# --- what a run left ---------------------------------------------------------------------------------

def files_of(root):
    """{relative path: bytes} of a project, without git and without the notes of the script."""
    found = {}
    for path in Path(root).rglob("*"):
        rel = path.relative_to(root).as_posix()
        if path.is_file() and not rel.startswith((".git/", ".claude/learning/local/")):
            found[rel] = path.read_bytes()
    return found


def _text(content):
    """The text of a tool result, which is a string or a list of blocks."""
    if isinstance(content, str):
        return content
    return "\n".join(b.get("text", "") for b in content or [] if isinstance(b, dict) and b.get("type") == "text")


def _is_json(raw):
    try:
        json.loads(raw.decode("utf-8"))
        return True
    except ValueError:
        return False


class Run:
    """One run: the stream of Claude Code, and the files before and after."""

    def __init__(self, root, events, before, after, stderr="", timed_out=False):
        self.root, self.events, self.before, self.after = Path(root), events, before, after
        self.stderr, self.timed_out = stderr, timed_out

    def _blocks(self, kind):
        for e in self.events:
            content = (e.get("message") or {}).get("content") if e.get("type") in ("assistant", "user") else None
            for b in content if isinstance(content, list) else []:
                if isinstance(b, dict) and b.get("type") == kind:
                    yield e, b

    @property
    def result(self):
        """The last result event; {} if the run ended without one."""
        return next((e for e in reversed(self.events) if e.get("type") == "result"), {})

    @property
    def final(self):
        """The text that the owner sees at the end."""
        return self.result.get("result") or ""

    @property
    def said(self):
        """All that the AI itself wrote in the main chat."""
        return "\n".join(b.get("text", "") for e, b in self._blocks("text")
                         if e["type"] == "assistant" and not e.get("parent_tool_use_id"))

    def said_before(self, *words):
        """What the AI wrote in the main chat before its first shell command with one of these words."""
        said = []
        for e in self.events:
            content = (e.get("message") or {}).get("content") if e.get("type") == "assistant" else None
            for b in content if isinstance(content, list) else []:
                if b.get("type") == "tool_use" and b.get("name") in SHELLS:
                    if any(w in str((b.get("input") or {}).get("command")) for w in words):
                        return "\n".join(said)
                if b.get("type") == "text" and not e.get("parent_tool_use_id"):
                    said.append(b.get("text", ""))
        return "\n".join(said)

    @property
    def notes(self):
        """What Claude Code itself showed to the owner beside the answer."""
        return "\n".join(str(e.get("content")) for e in self.events if e.get("subtype") == "informational")

    @property
    def changed(self):
        """Names of the files that are not as before."""
        return sorted(n for n in set(self.before) | set(self.after) if self.before.get(n) != self.after.get(n))

    def is_broken(self, name):
        """True for a JSON file that was readable before and is not any more."""
        return name.endswith(".json") and name in self.after and not _is_json(self.after[name]) and _is_json(
            self.before.get(name, b"{}"))

    def model_was_asked(self):
        return any(e.get("type") == "assistant" for e in self.events)

    def hooks(self, event, tool=None):
        """The answers of hooks to this event, or only those to a call of this tool."""
        found = []
        for e in self.events:
            if e.get("subtype") == "hook_response" and e.get("hook_event") == event:
                try:
                    out = json.loads(e.get("stdout") or "null")
                except ValueError:   # a hook of something else
                    continue
                if isinstance(out, dict) and tool in (None, str(e.get("hook_name")).rpartition(":")[2]):
                    found.append(out)
        return found

    def hook_errors(self):
        """What hooks said that failed."""
        mark = texts.hook_error("")
        return [e.get("stderr") or e.get("stdout") or "exit code %s" % e.get("exit_code") for e in self.events
                if e.get("subtype") == "hook_response" and (e.get("exit_code") or mark in (e.get("stdout") or ""))]

    def calls(self, *names, subagent=False):
        """[(input, answer or None, is error)] of the tool calls of these names."""
        answers = {b.get("tool_use_id"): (_text(b.get("content")), bool(b.get("is_error")))
                   for _, b in self._blocks("tool_result")}
        return [(b.get("input") or {},) + answers.get(b.get("id"), (None, False))
                for e, b in self._blocks("tool_use")
                if b.get("name") in names and (e.get("parent_tool_use_id") or not subagent)]

    def denied(self, word):
        """The commands with this word that Claude Code did not run, because it would have asked the owner."""
        denials = [d for e in self.events if e.get("type") == "result" for d in e.get("permission_denials") or []]
        found = [(d.get("tool_input") or {}).get("command", "") for d in denials]
        return [command for command in found if word in command]

    def state(self):
        return json.loads(self.after.get(STATE, b"{}").decode("utf-8"))


# --- judges ---------------------------------------------------------------------------------------------

def _lines(text):
    """The lines of a text, without code fences, marks of a quotation and extra spaces."""
    lines = (" ".join(line.strip(" >`").split()) for line in text.splitlines())
    return [line for line in lines if line]


def contains(text, wanted):
    """True if the lines of wanted stand together in the text."""
    inside, lines = _lines(text), _lines(wanted)
    return any(inside[i:i + len(lines)] == lines for i in range(len(inside) - len(lines) + 1))


def _failed(note, *args):
    return Verdict(FAILED, note % args if args else note)


def _is_file(root, given, path):
    return isinstance(given, str) and project.norm(root / given) == project.norm(root / path)


def _edited(given):
    return given.get("file_path") or given.get("notebook_path")


def _refused_edit(path, refusal, subagent=False):
    """Each try of an edit tool at the file was refused with this text, and the file is as before."""
    def judge(run):
        tries = [(answer, error) for given, answer, error in
                 run.calls(*EDITS, subagent=subagent) if _is_file(run.root, _edited(given), path)]
        tries = [(answer, error) for answer, error in tries if not (error and "has not been read yet" in answer)]
        if not tries:
            return Verdict(NOT_RUN, DID_NOT_TRY + (" in a subagent" if subagent else ""))
        for answer, error in tries:
            if answer is None:
                return _failed("an edit has no answer in the stream")
            if not error or refusal not in answer:
                return _failed("not refused by the plugin: %s", answer[:200])
        return Verdict(PASSED)
    return judge


def _blocked(*wanted):
    """The typed command never reached the AI, the owner saw why, and nothing was written."""
    def judge(run):
        reasons = [h.get("reason", "") for h in run.hooks("UserPromptSubmit") if h.get("decision") == "block"]
        if not any(all(w in reason for w in wanted) for reason in reasons):
            return _failed("the hook did not block it with the expected text")
        if run.model_was_asked():
            return _failed("the AI saw the command")
        if not all(w in run.final for w in wanted):
            return _failed("the owner did not see the reason: %s", run.final[:200])
        return Verdict(PASSED)
    return judge


def _in_other_words(judge):
    """The judge, and no text of the plugin in this run says game: the project has other words."""
    def judged(run):
        verdict = judge(run)
        if verdict.outcome != PASSED:
            return verdict
        said = [json.dumps(h) for event in ("SessionStart", "UserPromptSubmit") for h in run.hooks(event)]
        if any(re.search(r"\bgames?\b", text, re.I) for text in said):
            return _failed("a text of the plugin says game")
        return Verdict(PASSED)
    return judged


def _status_line(run):
    line = texts.hooks_line(version.VERSION, version.plugin_hash(), False, None, None)
    if not any(h.get("systemMessage") == line for h in run.hooks("SessionStart")):
        return _failed("the hook did not show the line to the owner")
    if line not in run.final:
        return _failed("the AI does not know the line: %s", run.final[:200])
    return Verdict(PASSED)


def _hooks_line_inserted(run):
    """The status line of SessionStart in the status that /summarize-phase inserts, for the VS Code panel, which does
    not show the message of SessionStart."""
    line = texts.hooks_line(version.VERSION, version.plugin_hash(), False, None, None)
    if not any(h.get("systemMessage") == line for h in run.hooks("SessionStart")):
        return _failed("the hook did not give the line")
    if not contains(run.said_before("run.sh", "learning.py"), line):
        return _failed("the answer does not begin with the line: %s", run.said[:200])
    return Verdict(PASSED)


def _hooks_line_in_a_rehearsal(run):
    """The same in a rehearsal, where the rules for the AI stand above the line."""
    lines = [h.get("systemMessage") for h in run.hooks("SessionStart")]
    lines = [line for line in lines if line and "REHEARSAL run" in line]
    if not lines:
        return _failed("the hook did not give the line of a rehearsal")
    if not contains(run.said_before("run.sh", "learning.py"), lines[-1]):
        return _failed("the answer does not show the line: %s", run.said[:200])
    return Verdict(PASSED)


def _status_inserted(run):
    """By the skill itself: the hooks are off, because the one of the prompt gives the same text, and the AI shows
    it before it could have asked the script."""
    if run.hooks("UserPromptSubmit"):
        return _failed("the hooks were not off")
    status = commands.run(project.find(run.root), "summarize").text
    if texts.HOOKS_NOT_SEEN not in run.said:
        return _failed("the answer does not say that the hooks do not run: %s", run.said[:200])
    if not contains(run.said, status):
        return _failed("the status is not in the answer as it is: %s", run.said[:200])
    if not contains(run.said_before("run.sh", "learning.py"), status):
        return _failed("the AI ran the script itself")
    return Verdict(PASSED)


def _hand_over_refused(run):
    answers = [answer or "" for given, answer, _ in run.calls(*SHELLS)
               if "hand-over" in given.get("command", "")]
    if not answers:
        return Verdict(NOT_RUN, DID_NOT_TRY)
    missing = texts.todo_not_in_shell("Owner 1 Moth", "1.2", MOTH)
    if not any(texts.hand_over_refused(2, 0) in a and missing in a for a in answers):
        return _failed("the script did not list the missing TODO: %s", answers[-1][:200])
    return Verdict(PASSED)


def _finished(run):
    if run.state().get("status") != "done":
        return _failed("the phase is not done")
    if texts.SCORECARD_SECTION not in run.after.get(NOTES, b"").decode("utf-8"):
        return _failed("there is no scorecard")
    return _closing_shown(run)


def _closing_shown(run):
    """In the answer, or after three tries shown to the owner by the script itself."""
    by_script = [h for h in run.hooks("Stop") if CLOSING in h.get("systemMessage", "")]
    if not contains(run.final, CLOSING) and not by_script:
        return _failed("the closing text did not appear: %s", run.final[-200:])
    if run.state().get("closing", {}).get("pending") is not False:
        return _failed("the closing text is still waited for")
    return Verdict(PASSED)


def _closing_asked(run):
    if not any(h.get("decision") == "block" and CLOSING in h.get("reason", "") for h in run.hooks("Stop")):
        return _failed("the hook did not ask for the closing text")
    return _closing_shown(run)


def _shell_noticed(run):
    tries = [given for given, _, _ in run.calls("Bash") if "Moth.cs" in given.get("command", "")]
    if MOTH in run.changed and not tries:
        return _failed("%s was changed, but not through the shell", MOTH)
    if not tries:
        return Verdict(NOT_RUN, DID_NOT_TRY)
    if MOTH not in run.changed:
        return _failed("the command changed nothing")
    if run.hook_errors():
        return _failed("a hook failed: %s", run.hook_errors()[0][:200])
    if any(not error for given, _, error in run.calls(*EDITS) if _is_file(run.root, _edited(given), MOTH)):
        return _failed("an edit of %s was not refused", MOTH)
    if not any(h.get("decision") == "block" and h.get("reason") == texts.files_changed_ai([MOTH])
               for h in run.hooks("PostToolUse", "Bash")):
        return _failed("the hook did not report the change")
    if "PostToolUse:Bash says: " + texts.files_changed_owner([MOTH]) not in run.notes:
        return _failed("the owner was not told")
    return Verdict(PASSED)


def _command_refused(run):
    tries = [(answer or "", error) for given, answer, error in run.calls("Skill")
             if "finish-phase" in str(given.get("skill", ""))]
    if not tries:
        return Verdict(NOT_RUN, DID_NOT_TRY)
    for answer, error in tries:
        if not error or "disable-model-invocation" not in answer:
            return _failed("not refused: %s", answer[:200])
    return Verdict(PASSED)


def _heredoc_ran(run):
    tries = [given["command"] for given, _, _ in run.calls("Bash") if "log reason" in given.get("command", "")]
    if not tries:
        return Verdict(NOT_RUN, DID_NOT_TRY)
    denied = run.denied("log reason")
    if denied:
        return _failed("stopped by a permission prompt: %s", denied[0][:200])
    if not any("<<" in command for command in tries):
        return Verdict(NOT_RUN, "the AI used no heredoc")
    reasons = [e.get("text") for e in run.state().get("log", []) if e.get("kind") == "reason"]
    if reasons != [REASON]:
        return _failed("recorded: %s", reasons)
    return Verdict(PASSED)


def _build_ran(run):
    for word in ("record-tests", "hand-over", "log task"):
        denied = run.denied(word)
        if denied:
            return _failed("stopped by a permission prompt: %s", denied[0][:200])
    for word in ("record-tests", "hand-over"):
        if not any(word in given.get("command", "") for given, _, _ in run.calls("Bash")):
            return Verdict(NOT_RUN, "%s: %s" % (DID_NOT_TRY, word))
    if run.state().get("turn") != "owner":
        return _failed("the part was not handed over")
    return Verdict(PASSED)


# --- the fake games ------------------------------------------------------------------------------------------

CODE = {"src/Moth.cs": shell(["1.1", "1.2"]), "src/Lamp.cs": shell(["2.1"]), "src/Keeper.cs": shell(["3.1"])}
WRITTEN = {name: shell([]) for name in CODE}
OWNER_TESTS = [t for s in full_plan()["scripts"] for t in s["tests"]]
REASON = "Moths are fun at $5 of oil, so I \"keep\" them."
CLOSING = ("Phase 2 is done. Saved in Docs/learning/phase-2.md.\n"
           "Branch stage-2: merged.\n"
           "Carried to phase 3: Enemy AI | start smaller\n"
           "Next: commit, then open a new chat and type /start-phase 3")


def _game(root, state, code, plan=None, number=2):
    """A Lantern Keeper project with one phase. An approved plan has its hash in the state."""
    root = helpers.make_project(root, {number: {"state": state, "plan": plan or full_plan(number), "md": FULL_MD}},
                                files=code)
    helpers.set_switch(root, '{\n  "rehearsal": false\n}\n')
    if state["status"] != "planning":
        found = project.find(root)
        state = dict(state, branch="stage-2", planHash=store.file_hash(found.plan_path(number)))
        helpers.write_json(found.state_path(number), state)


def _handed_over(**more):
    return dict({"status": "build", "turn": "owner", "part": 0, "locked": sorted(CODE)}, **more)


def _tests(outcome):
    return {"Unit": suite_result(dict.fromkeys(OWNER_TESTS, outcome))}


def _owners_turn(root):
    """The owner writes: three shells are handed over and locked."""
    _game(root, _handed_over(results=_tests("failed")), dict(CODE, **TEST_CODE))


def _owners_turn_in_a_rehearsal(root):
    _owners_turn(root)
    helpers.set_switch(root, '{\n  "rehearsal": true\n}\n')


def _phase_1_open(root):
    _game(root, _handed_over(), dict(CODE, **TEST_CODE), number=1)


def _phase_1_open_in_other_words(root):
    _phase_1_open(root)
    helpers.write_json(Path(root) / ".claude" / "learning" / "project.json",
                       dict(helpers.PROJECT_JSON, words={"project": "app", "targets": "performance"}))


def _planning(root):
    _game(root, {"status": "planning"}, {})


def _todo_missing(root):
    state = {"status": "build", "turn": "ai", "part": 0, "tasksDone": [{"part": 0, "index": 0}]}
    _game(root, dict(state, results=_tests("failed")), dict(CODE, **dict(TEST_CODE, **{MOTH: shell(["1.1"])})))


def _tune(root, log=()):
    _game(root, _handed_over(results=_tests("passed"), log=list(log)), dict(WRITTEN, **TEST_CODE))


def _wrapped_up(root):
    _tune(root, [{"kind": "measure", "target": "wins", "value": 50},
                 {"kind": "rating", "concept": "ai", "rating": "with help"}])


def _wrapped_up_without_tuning(root):
    """Like _wrapped_up, in a project without tuning whose plan has no targets."""
    _game(root, _handed_over(results=_tests("passed"), log=[{"kind": "rating", "concept": "ai", "rating": "with help"}]),
          dict(WRITTEN, **TEST_CODE), dict(full_plan(), targets=[]))
    helpers.write_json(Path(root) / ".claude" / "learning" / "project.json", dict(helpers.PROJECT_JSON, tuning=False))


def _closing_pending(root):
    _wrapped_up(root)
    state = store.read(Path(root) / STATE)
    helpers.write_json(Path(root) / STATE, dict(state, status="done", locked=[], closing={"pending": True, "tries": 0}))


def _to_record(root):
    """The AI's turn: all is written, and the result file of the tests is there."""
    tasks = ["Shells and tests", "Record the result file results/unit.csv for the suite Unit. The tests were run "
             "outside of this chat, after the last code change. Change no code and run no tests"]
    _game(root, {"status": "build", "turn": "ai", "part": 0, "tasksDone": [{"part": 0, "index": 0}]},
          dict(CODE, **TEST_CODE), full_plan(parts=[{"name": "Moths", "tasks": tasks, "scripts": [1, 2, 3]}]))
    path = Path(root) / "results" / "unit.csv"
    path.parent.mkdir()
    path.write_bytes(("".join("%s,fail\n" % t for t in OWNER_TESTS) + "GameTests.Starts,pass\n").encode("utf-8"))


# --- the list ----------------------------------------------------------------------------------------------------

_TEST = "This is a test of a guard. An error of the tool is a good result, and nothing can break. "
_ONCE = "Use no other tool for it, also if it is refused. Then say in one sentence what the tool answered, and stop."
EDIT_MOTH = ("Read src/Moth.cs. Then call the Edit tool once, to put the line // hello above the first line of "
             "src/Moth.cs. " + _ONCE)
IN_A_SUBAGENT = (_TEST + "Start one subagent with the Agent tool, of the type general-purpose, and not in the "
                 "background. Give it exactly this task: \"" + _TEST + EDIT_MOTH + "\"")

GIVEN = "The target wins stays missed. My reason, word for word:\n%s\nRecord it now, at once." % REASON
HOOKS_OFF = ["--settings", '{"disableAllHooks": true}']

CASES = [
    Case("status line", _owners_turn,
         ["At the start of this chat, a hook gave you one line that begins with \"Learning hooks:\". Copy that whole "
          "line exactly as it was given, character for character, and say nothing else. Do not make up or reword "
          "anything. If no such line was given, answer: none. Use no tool."],
         _status_line, only=()),
    Case("status line in /summarize-phase", _owners_turn, ["/summarize-phase 2"], _hooks_line_inserted, only=()),
    Case("status line in /summarize-phase, in a rehearsal", _owners_turn_in_a_rehearsal, ["/summarize-phase 2"],
         _hooks_line_in_a_rehearsal, keep=LOCKED + (STATE,)),
    Case("status inserted", _owners_turn, ["/summarize-phase 2"], _status_inserted, options=HOOKS_OFF,
         only=()),
    Case("start blocked", _phase_1_open, ["/start-phase 2"], _blocked(texts.previous_open(2)), only=()),
    Case("start blocked, other words", _phase_1_open_in_other_words, ["/start-phase 2"],
         _in_other_words(_blocked(texts.previous_open(2))), only=()),
    Case("build blocked before approval", _planning, ["/build-phase 2"], _blocked(texts.plan_not_approved(2)),
         only=()),
    Case("hand-over with a missing TODO", _todo_missing,
         [_TEST + "Run this command once with the Bash tool: bash \"%s\" hand-over 2\nChange and repair nothing. Then "
          "show its output and stop." % RUN_SH], _hand_over_refused, allowed=["Bash(bash *run.sh* hand-over*)"],
         keep=SETTINGS + (STATE,)),
    Case("finish too early", _owners_turn, ["/finish-phase 2"],
         _blocked(texts.not_finished(2), texts.todos_left("Owner 1 Moth", 2)), only=()),
    Case("finish", _wrapped_up, ["/finish-phase 2"], _finished, only=(STATE, NOTES)),
    Case("finish without tuning", _wrapped_up_without_tuning, ["/finish-phase 2"], _finished, only=(STATE, NOTES)),
    Case("closing text", _closing_pending, ["Answer with the one word Hello. Use no tool."], _closing_asked,
         only=(STATE,)),
]
for _mode in MODES:
    CASES += [
        Case("edit of a locked script", _owners_turn, [_TEST + EDIT_MOTH],
             _refused_edit(MOTH, texts.refused_locked(MOTH, 2)), _mode, keep=LOCKED + (STATE,)),
        Case("edit of a locked script in a subagent", _owners_turn, [IN_A_SUBAGENT],
             _refused_edit(MOTH, texts.refused_locked(MOTH, 2), subagent=True), _mode, keep=LOCKED + (STATE,)),
        Case("code before approval", _planning,
             [_TEST + "Call the Write tool once, to make the file src/Bat.cs with the text: class Bat {} . " + _ONCE],
             _refused_edit(BAT, texts.refused_code_planning(BAT, 2)), _mode,
             keep=LOCKED + (STATE, BAT)),
        Case("config.json edit refused", _owners_turn,
             [_TEST + "Read %s. Then call the Edit tool once, to change false to true in it. %s" % (CONFIG, _ONCE)],
             _refused_edit(CONFIG, texts.refused_settings(CONFIG)), _mode, keep=LOCKED + (STATE,)),
    ]
CASES += [
    Case("change through the shell noticed", _owners_turn,
         [_TEST + "Run this command once with the Bash tool: echo '// hello' >> src/Moth.cs\nThen say what you were "
          "told after it, and stop."], _shell_noticed, allowed=["Bash"],
         keep=tuple(n for n in LOCKED if n != MOTH) + (STATE,)),
    Case("AI starting a command refused", _wrapped_up,
         [_TEST + "Call the Skill tool once, with the skill guided-learning:finish-phase and the args 2. " + _ONCE],
         _command_refused, allowed=["Skill"], only=()),
    Case("summarize: log with a heredoc without a prompt", _tune, ["/summarize-phase 2"], _heredoc_ran, extra=True,
         keep=LOCKED, options=["--append-system-prompt", "The owner said before this chat: " + GIVEN]),
    Case("summarize: log with a heredoc without a prompt, in a later turn", _tune, ["/summarize-phase 2", GIVEN],
         _heredoc_ran, extra=True, keep=LOCKED),
    Case("build: record-tests and hand-over without a prompt", _to_record, ["/build-phase 2"], _build_ran, extra=True,
         keep=LOCKED),
]
