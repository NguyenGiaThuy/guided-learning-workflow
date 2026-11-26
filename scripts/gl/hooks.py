"""What the plugin answers to the hooks of Claude Code.

PreToolUse refuses edits of the owner's and the workflow's files; PostToolUse notices changes that
came by another route; UserPromptSubmit runs the owner's commands; Stop asks for the closing text.
"""
import hashlib
import json
import os
import re
import time
from collections import namedtuple
from pathlib import Path

from . import commands, project, rehearsal, render, scan, state, store, texts
from .project import LEARNING, inside, norm

REHEARSAL_FILES = (LEARNING / "rehearsal").as_posix() + "/"
EDIT_TOOLS = {"Edit": "file_path", "Write": "file_path", "MultiEdit": "file_path",
              "NotebookEdit": "notebook_path"}
POST_EVENTS = ("PostToolUse", "PostToolUseFailure")
MAX_TRIES = 3
DAY = 24 * 3600
_NOTE_WAIT = 2.0    # seconds to wait for a script that is just writing a phase file
_NOTE_PAUSE = 0.01

# One file the hooks compare before and after a tool call: its name relative to the chat's project,
# the file itself, the project.json of its project, and for a phase-N.json the script's note of it.
Watched = namedtuple("Watched", "name path home note")

# Why an edit is not allowed: workflow, locked, planning, unbuilt or todo, and the text.
Refusal = namedtuple("Refusal", "kind text")


class HookError(Exception):
    """A hook input that cannot be used, in words for the user."""


# --- the edited file ------------------------------------------------------------------------------

def _real_path(text, base):
    """The file an edit tool would open for this spelling of a path."""
    path = os.path.expanduser(text.strip())
    if os.name == "nt":
        path = path.replace("/", "\\")
        path = re.sub(r"^\\\\[?.]\\(UNC\\)?", lambda m: "\\\\" if m.group(1) else "", path, flags=re.I)
        path = re.sub(r"^\\(?:cygdrive\\)?([a-z])(?=\\|$)", r"\1:", path, flags=re.I)   # the drives of bash
        drive, rest = os.path.splitdrive(path)
        path = drive + rest.split(":")[0].rstrip(" .")   # Windows ignores the end, and a stream is the same file
    return os.path.realpath(os.path.join(base, path))


def _edited_file(data, cwd):
    """The real path of the file an edit tool is about to change; None for any other tool."""
    key = EDIT_TOOLS.get(data.get("tool_name"))
    if key is None:
        return None
    tool_input = data.get("tool_input")
    path = tool_input.get(key) if isinstance(tool_input, dict) else None
    if not isinstance(path, str) or not path.strip():
        raise HookError(texts.HOOK_NO_PATH)
    base = data.get("cwd")
    return _real_path(path, base if isinstance(base, str) and base else cwd)


# --- the projects and their phases ------------------------------------------------------------------

def _with_active(found):
    return [found, found.active] if found.rehearsal else [found]


def _guarding(found, target):
    """The projects whose rules hold for the file: the chat's and the file's own, each with its rehearsal."""
    projects = _with_active(found) if found else []
    own = project.find(os.path.dirname(target))
    if own and not (found and norm(own.root) == norm(found.root)):
        projects += _with_active(own)
    return projects


def _phases(p):
    """[(number, state data)] of the phases that have a state file."""
    return [(n, store.read(p.state_path(n))) for n in p.phase_numbers() if p.state_path(n).exists()]


def _status(data):
    return data.get("status") or "planning"


def _locked(data):
    """Paths of the owner scripts that are locked in a phase."""
    paths = data.get("locked")
    if _status(data) in ("done", "skipped") or not isinstance(paths, list):
        return []
    return [p for p in paths if isinstance(p, str)]


def _is_approved(data):
    return _status(data) == "build" or bool(data.get("planHash"))


def _name(p, path):
    """A path as the owner knows it, relative to the project."""
    try:
        return os.path.relpath(path, p.root).replace(os.sep, "/")
    except ValueError:   # another drive
        return str(path)


# --- PreToolUse: refusing --------------------------------------------------------------------------

def _workflow_refusal(p, phases, target, name):
    learning = p.root / LEARNING
    if inside(target, learning / "local") or inside(target, learning / "rehearsal-reports"):
        return texts.refused_local(name)
    if norm(target) in (norm(learning / "project.json"), norm(learning / "config.json")):
        return texts.refused_settings(name)
    if norm(os.path.dirname(target)) != norm(p.docs):
        return None
    m = re.fullmatch(r"phase-([0-9]+)(\.plan)?\.json", os.path.normcase(os.path.basename(target)))
    if not m:
        return None
    if not m.group(2):
        return texts.refused_state(name)
    n = int(m.group(1))
    if any(number == n and _is_approved(data) for number, data in phases):
        return texts.refused_plan(name, n)
    return None


def _in_code(p, target):
    """True for a file in a code folder. Plans, notes and .claude/learning with the rehearsal are no code,
    also if a code folder holds them."""
    if inside(target, p.root / LEARNING):
        return False
    if norm(os.path.dirname(target)) == norm(p.docs) and re.fullmatch(
            r"phase-[0-9]+(\.plan\.json|\.md)", os.path.normcase(os.path.basename(target))):
        return False
    return any(inside(target, d) for d in p.code_dirs)


def _code_refusal(p, phases, target, name):
    if not _in_code(p, target):
        return None
    for n, data in phases:
        if _status(data) == "planning":
            return Refusal("planning", texts.refused_code_planning(name, n))
        if _status(data) == "build" and not data.get("turn"):
            return Refusal("unbuilt", texts.refused_code_unbuilt(name, n))
    return None


def _is_planned(p, target):
    """True if the file is an owner script of a plan. A plan that is being written may be unusable."""
    for n in p.phase_numbers():
        try:
            scripts = store.read(p.plan_path(n)).get("scripts")
        except store.BadJson:
            continue
        for s in scripts if isinstance(scripts, list) else []:
            path = s.get("path") if isinstance(s, dict) else None
            if isinstance(path, str) and path and norm(p.root / path) == norm(target):
                return True
    return False


def _todo_refusal(p, target, name, lost):
    if lost and (_in_code(p, target) or _is_planned(p, target)):
        return Refusal("todo", texts.refused_todo(name, lost))
    return None


def _refusal(p, target, lost):
    """The Refusal of an edit of the file by the project, or None."""
    name, phases = _name(p, target), _phases(p)
    text = _workflow_refusal(p, phases, target, name)
    if text:
        return Refusal("workflow", text)
    for n, data in phases:
        if any(norm(p.root / path) == norm(target) for path in _locked(data)):
            return Refusal("locked", texts.refused_locked(name, n))
    for n, entry in p.open_phases().items():
        away = any(norm(p.root / path) == norm(target) for path in entry["locked"]) and state.open_elsewhere(p, n)
        if away:
            return Refusal("locked", texts.refused_locked_elsewhere(name, n, away[0]))
    return _code_refusal(p, phases, target, name) or _todo_refusal(p, target, name, lost)


# --- PreToolUse: the text after the edit ---------------------------------------------------------------

def _plain(text):
    return text.replace("\r\n", "\n")


def _replaced(text, edit):
    """The text after one replacement; None if the tool itself will fail."""
    if not isinstance(edit, dict):
        return None
    old, new = edit.get("old_string"), edit.get("new_string")
    if not isinstance(old, str) or not isinstance(new, str):
        return None
    old, new = _plain(old), _plain(new)
    if not old or old not in text:
        return None
    return text.replace(old, new) if edit.get("replace_all") else text.replace(old, new, 1)


def _cell_text(cell):
    source = cell.get("source", "")
    return "".join(source) if isinstance(source, list) else source


def _notebook_lost(text, edit):
    """TODO ids that an edit of a notebook removes, as far as its input tells."""
    if edit.get("edit_mode") == "insert":
        return []
    try:
        cells = json.loads(text)["cells"]
        ids = [c.get("id") or "cell-%d" % i for i, c in enumerate(cells)]
        sources = [_cell_text(c) for c in cells]
        wanted = edit.get("cell_id")
        if wanted not in ids:
            wanted = {"cell-%d" % i: c for i, c in enumerate(ids)}[wanted]
        after = list(sources)
        after[ids.index(wanted)] = "" if edit.get("edit_mode") == "delete" else edit["new_source"]
        return scan.removed("\n".join(sources), "\n".join(after))
    except (ValueError, KeyError, TypeError, AttributeError):
        return []   # no such notebook or cell: the tool fails by itself


def _lost_todos(data, target):
    """TODO ids that the file holds now and would not hold after the edit."""
    if not os.path.isfile(target):
        return []
    text = _plain(store.read_bytes(target).decode("utf-8", errors="replace").lstrip("﻿"))
    if not scan.TODO.search(text):
        return []
    tool, tool_input = data["tool_name"], data["tool_input"]
    if tool == "NotebookEdit":
        return _notebook_lost(text, tool_input)
    if tool == "Write":
        after = tool_input.get("content")
        return scan.removed(text, after) if isinstance(after, str) else []
    edits = tool_input.get("edits") if tool == "MultiEdit" else [tool_input]
    after = text
    for edit in edits if isinstance(edits, list) else []:
        after = _replaced(after, edit)
        if after is None:
            return []
    return scan.removed(text, after)


# --- PreToolUse ------------------------------------------------------------------------------------------

def _deny(text):
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                   "permissionDecisionReason": text}}


def _refuse_edit(found, data, target):
    """The answer that refuses the edit, or None. found is the chat's project, or None."""
    guarding = _guarding(found, target)
    lost = _lost_todos(data, target) if guarding else []
    for p in guarding:
        refused = _refusal(p, target, lost)
        if refused:
            return _deny("\n".join([refused.text] + _note_refusal(found, p, refused.kind, data)))
    return None


def _note_refusal(found, p, kind, data):
    """Tick a refused edit of the fake project in the rehearsal of this chat."""
    if found and found.rehearsal and kind in rehearsal.REFUSED and norm(p.root) == norm(found.rehearsal_folder):
        return rehearsal.note(found, rehearsal.REFUSED[kind], data.get("session_id"))
    return []


def _pre_tool_use(found, data, cwd):
    target = _edited_file(data, cwd)
    refused = _refuse_edit(found, data, target) if target else None
    if refused is None:
        _take_snapshot(found, data.get("tool_use_id"))
    return refused


def _edit_from_outside(data, cwd):
    """An edit in a chat without a project: only a file of a game is guarded, all else is silent."""
    try:
        target = _edited_file(data, cwd)
    except (HookError, OSError, ValueError, TypeError):
        return None   # no usable path; a project that cannot be read is an error, though
    return _refuse_edit(None, data, target) if target else None


# --- snapshots ---------------------------------------------------------------------------------------------

def _snapshot_path(root, tool_use_id):
    """The file of this tool call; None if it has no id."""
    if not isinstance(tool_use_id, str) or not tool_use_id:
        return None
    name = tool_use_id
    if not re.fullmatch(r"[A-Za-z0-9_]{1,100}", name):
        name = hashlib.sha256(name.encode("utf-8", "surrogatepass")).hexdigest()
    return Path(root) / LEARNING / "local" / "snapshots" / (name + ".json")


def _watched(outer, tolerant=False):
    """The files that are compared, of the project and of its rehearsal.

    tolerant: leave out what cannot be read, because the tool call may have broken it.
    """
    found = []

    def add(p, path, note=None):
        home = _name(outer, p.root / LEARNING / "project.json")
        found.append(Watched(_name(outer, path), path, home, note and _name(outer, note)))

    try:
        projects = _with_active(outer)
    except store.BadJson:
        if not tolerant:
            raise
        projects = [outer]
    for p in projects:
        add(p, p.root / LEARNING / "project.json")
        add(p, p.root / LEARNING / "config.json")
        for n in p.phase_numbers():
            add(p, p.state_path(n), p.note_path(n))
            try:
                data = store.read(p.state_path(n))
            except store.BadJson:
                if not tolerant:
                    raise
                continue
            if _is_approved(data):
                add(p, p.plan_path(n))
            for path in _locked(data):
                add(p, p.root / path)
    return found


def _hash(path):
    """The hash of a file; None if there is none."""
    if not os.path.isfile(path):
        return None
    try:
        return store.file_hash(path)
    except FileNotFoundError:
        return None


def _take_snapshot(outer, tool_use_id):
    path = _snapshot_path(outer.root, tool_use_id)
    if path is None:
        return
    files = {w.name: {"hash": _hash(w.path), "note": w.note} for w in _watched(outer)}
    store.write(path, {"files": files, "run": _run(outer)})
    _delete_old(path.parent)


def _run(outer):
    """The run of the rehearsal; None if there is none."""
    return render.run_number(outer) if outer.rehearsal else None


def _delete_old(folder):
    limit = time.time() - DAY
    for name in os.listdir(folder):
        try:
            if os.stat(folder / name).st_mtime < limit:
                os.remove(folder / name)
        except OSError:
            pass   # another chat deleted it


def _read_snapshot(path):
    """(files, run) of a snapshot, which is deleted; (None, None) if there is none."""
    if not path.is_file():
        return None, None
    try:
        data = store.read(path)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass   # deleted later, when it is a day old
    files = data.get("files")
    if not isinstance(files, dict) or not all(isinstance(f, dict) for f in files.values()):
        raise HookError(texts.HOOK_SNAPSHOT)
    return files, data.get("run")


# --- PostToolUse -----------------------------------------------------------------------------------------------

def _noted(note):
    try:
        return store.read(note).get("hash")
    except (store.BadJson, OSError):
        return None


def _by_script(path, note):
    """True if the file is as the script left it. The note comes a moment after the file, so a
    script that is just writing is waited for."""
    end = time.monotonic() + _NOTE_WAIT
    looks = 0
    while True:
        writing = os.path.exists(str(path) + ".lock")   # first, so that it holds for the values read next
        current = _hash(path)
        if current is not None and current == _noted(note):
            return True
        looks += 1
        if (looks > 1 and not writing) or time.monotonic() >= end:
            return False
        time.sleep(_NOTE_PAUSE)


def _changed(root, files, outer):
    """Names of the files that are not as in the snapshot, without the changes of the script."""
    before = {name: (f.get("hash"), f.get("note")) for name, f in files.items()}
    try:
        now = _watched(outer, tolerant=True) if outer else []
    except Exception:   # the tool call left settings of a wrong type; the snapshot still tells what changed
        now = []
    for w in now:
        if w.note and w.home in files:   # a phase that was not there before, in a project watched before
            before.setdefault(w.name, (None, w.note))
    names = []
    for name, (old, note) in before.items():
        path = os.path.join(root, name)
        if _hash(path) != old and not (note and _by_script(path, os.path.join(root, note))):
            names.append(name)
    return sorted(names)


def _report(event, root, outer, data):
    path = _snapshot_path(root, data.get("tool_use_id"))
    files, run = _read_snapshot(path) if path else (None, None)
    names = _changed(root, files, outer) if files is not None else []
    if outer and outer.rehearsal and run != _run(outer):   # made again meanwhile, by the script
        names = [n for n in names if not n.startswith(REHEARSAL_FILES)]
    if not names:
        return None
    answer = {"systemMessage": texts.files_changed_owner(names)}
    if event == "PostToolUse":
        answer.update(decision="block", reason=texts.files_changed_ai(names))
    else:
        answer["hookSpecificOutput"] = {"hookEventName": event, "additionalContext": texts.files_changed_ai(names)}
    return answer


def _post_tool_use(found, data, cwd):
    return _report("PostToolUse", found.root, found, data)


def _post_tool_use_failure(found, data, cwd):
    return _report("PostToolUseFailure", found.root, found, data)


def _report_lost_project(event, data, cwd):
    """project.json is gone or broken, but a snapshot of this very tool call shows what was there."""
    folder = Path(os.path.realpath(cwd))
    for d in [folder] + list(folder.parents):
        path = _snapshot_path(d, data.get("tool_use_id"))
        if path and path.is_file():
            return _report(event, d, None, data)
    return None


# --- the other events ----------------------------------------------------------------------------------------------

def _session_start(found, data, cwd):
    line = render.one_line(found)
    try:   # for `status session=<id>`: a panel that does not show this message still gets the line from there
        found.note_session(data.get("session_id"))
    except Exception:   # the line matters more than the record
        pass
    context = line + "\n" + rehearsal.rules(found) if found.rehearsal else line
    return {"systemMessage": line,
            "hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": context}}


def _user_prompt_submit(found, data, cwd):
    parsed = commands.parse(data.get("prompt"))
    if parsed is None or parsed[0] == "setup-learning":   # the skill handles it
        return None
    out = rehearsal.run(found, *parsed, session=data.get("session_id"))
    if not out.ok:
        return {"decision": "block", "reason": out.text}
    return {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": out.text}}


def _lines(text):
    return [line.strip() for line in text.splitlines() if line.strip()]


def _contains(message, text):
    """True if the lines of text stand together in the message; spaces and blank lines do not count."""
    inside, wanted = _lines(message), _lines(text)
    return any(inside[i:i + len(wanted)] == wanted for i in range(len(inside) - len(wanted) + 1))


class _NotPending(Exception):
    """Leaves an update_state callback without writing: the text is not waited for any more."""


def _pending(data):
    closing = data.get("closing")
    return isinstance(closing, dict) and bool(closing.get("pending"))


def _settle(p, n, present):
    """Count a try or clear the mark. True if the answer must be asked for once more."""
    asked = []

    def apply(data):
        if not _pending(data):
            raise _NotPending()
        tries = data["closing"].get("tries")
        tries = tries if isinstance(tries, int) else 0
        asked[:] = [] if present or tries >= MAX_TRIES else [True]
        data["closing"] = {"pending": bool(asked), "tries": tries + len(asked)}

    try:
        p.update_state(n, apply)
    except _NotPending:
        return None
    return bool(asked)


def _stop(found, data, cwd):
    active = found.active
    message = data.get("last_assistant_message")
    message = message if isinstance(message, str) else ""
    asked, given_up, warnings = [], [], []
    for n, phase in _phases(active):
        if not _pending(phase):
            continue
        text = commands.closing_text(active, n)
        present = _contains(message, text)
        again = _settle(active, n, present)
        if again:
            asked.append(text)
        elif again is False and not present:
            given_up.append(text)
        elif again is False and found.rehearsal:
            warnings += rehearsal.note(found, "closing-text", data.get("session_id"))
    answer = {}
    if asked:
        answer.update(decision="block", reason=texts.closing_asked("\n".join(asked)))
    if given_up or warnings:
        answer["systemMessage"] = "\n".join(given_up + warnings)
    return answer or None


# --- dispatch -----------------------------------------------------------------------------------------------------------

_HANDLERS = {"SessionStart": _session_start, "UserPromptSubmit": _user_prompt_submit, "PreToolUse": _pre_tool_use,
             "PostToolUse": _post_tool_use, "PostToolUseFailure": _post_tool_use_failure, "Stop": _stop}
EVENTS = tuple(_HANDLERS)


def _outside(event, data, cwd):
    """No project here. A file of a game may still be edited, or project.json just have gone."""
    if not isinstance(data, dict):
        return None
    if event == "PreToolUse":
        return _edit_from_outside(data, cwd)
    if event in POST_EVENTS:
        return _report_lost_project(event, data, cwd)
    return None


def _error(event, error):
    """The answer of a hook that failed: refuse what can be refused, else only say so."""
    if isinstance(error, (HookError, rehearsal.RehearsalError, store.BadJson, store.LockTimeout, OSError)):
        text = texts.hook_error(error)
    else:
        text = texts.unexpected_error(error)
    if event == "PreToolUse":
        return _deny(text)
    if event == "UserPromptSubmit":
        return {"decision": "block", "reason": text}
    return {"systemMessage": text}


def handle(event, data, cwd):
    """The answer to one hook call: a dict, or None for nothing."""
    if event not in _HANDLERS:
        return None
    try:
        try:
            found = project.find(cwd)
        except store.BadJson:
            reported = _outside(event, data, cwd) if event in POST_EVENTS else None
            if reported is None:
                raise
            return reported   # the tool call broke project.json, and the snapshot tells what else it changed
        if found is None:
            return _outside(event, data, cwd)
        rehearsal.sync(found)
        if not isinstance(data, dict):
            raise HookError(texts.HOOK_INPUT)
        return _HANDLERS[event](found, data, cwd)
    except Exception as e:
        return _error(event, e)


def answer(event, raw):
    """The output for the bytes of stdin: one JSON line, or an empty text."""
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except Exception:   # handle() says so, if there is a project
        data = None
    given = data.get("cwd") if isinstance(data, dict) else None
    try:
        cwd = os.environ.get("CLAUDE_PROJECT_DIR") or (given if isinstance(given, str) and given else os.getcwd())
    except OSError:   # the working folder is gone, and with it any project
        return ""
    result = handle(event, data, cwd)
    if result is None:
        return ""
    return result if isinstance(result, str) else json.dumps(result)
