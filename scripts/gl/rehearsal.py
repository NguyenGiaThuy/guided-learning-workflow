"""The rehearsal: a fake project in .claude/learning/rehearsal, made again at each restart.

sync() makes it. The simulation stands in for tests, merge and branch. The checklist is ticked as far
as the script sees the outcome. Only sync() deletes, and only inside <root>/.claude/learning/rehearsal.
"""
import json
import os
import re
import stat
import time
from collections import namedtuple
from pathlib import Path

from . import commands, render, results, scan, state, store, texts, version
from .project import LEARNING, Project, inside, norm

TEMPLATE = version.ROOT / "rehearsal" / "project"
CHECKLIST = version.ROOT / "rehearsal" / "checklist.md"
SETTINGS = (LEARNING / "project.json").as_posix()
WORDS = ("pass", "fail", "merge", "branch", "check", "report")
WRONG_BRANCH = "main"
WITH_RULES = ("build-phase", "summarize-phase")   # the AI shows the text of the others to the owner as it is
REFUSED = {"locked": "edit-locked", "planning": "edit-unapproved"}   # kind of a refused edit: its check
_NAME_SURROGATE = 0x20000000   # the bit of a reparse tag that stands for another place (not for a cloud file)

Check = namedtuple("Check", "id covers type expect by")


class RehearsalError(Exception):
    """Something the rehearsal cannot do, in words for the user."""


class _Nothing(Exception):
    """Leaves an update_local callback without writing: there is nothing to do."""


# --- files of the outer project ----------------------------------------------------------------

SEEN = "seen.json"
RUNS = "rehearsal-runs"


def _local(project):
    return project.root / LEARNING / "local"


def _record_name(run):
    return "%s/run-%d.json" % (RUNS, run)


def report_path(project, run):
    return project.root / LEARNING / "rehearsal-reports" / ("run-%d.md" % run)


def _seen(project):
    """What was noted at the last restart; a damaged note is as good as none."""
    try:
        return store.read(_local(project) / SEEN)
    except store.BadJson:
        return {}   # replaced at the restart, inside the lock


def _numbers(folder):
    """The run numbers of the files in a folder."""
    names = os.listdir(folder) if os.path.isdir(folder) else []
    found = [re.fullmatch(r"run-([0-9]{1,9})\.(?:json|md)", name) for name in names]
    return [int(m.group(1)) for m in found if m]


def _record(project, run):
    """The record of a run; {} if there is none or it is damaged."""
    try:
        return store.read(_local(project) / _record_name(run))
    except store.BadJson:
        return {}


def _ticks_of(record):
    found = record.get("ticks")
    return {k: v for k, v in found.items() if isinstance(v, dict)} if isinstance(found, dict) else {}


# --- the folder that is deleted and made again -----------------------------------------------------

def _is_link(path):
    """True for a symbolic link and for a Windows junction. False for what is not there."""
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return False
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_reparse_tag", 0) & _NAME_SURROGATE)


def _checked_folder(project):
    """<root>/.claude/learning/rehearsal. Refused unless it is (or can become) a real folder at exactly
    that place, with nothing of the real project in it."""
    folder = os.path.join(os.path.realpath(project.root), ".claude", "learning", "rehearsal")
    if os.path.lexists(folder) and (_is_link(folder) or not os.path.isdir(folder)):
        raise RehearsalError(texts.rehearsal_not_usable(folder))
    if norm(folder) != os.path.normcase(folder):   # .claude or learning is a link
        raise RehearsalError(texts.rehearsal_not_usable(folder))
    for real in [project.docs] + project.code_dirs:
        if inside(real, folder):
            raise RehearsalError(texts.rehearsal_real_folder(real, folder))
    return Path(folder)


def _remove_file(path):
    def remove():
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass   # another process removed it
        except PermissionError:
            if _is_link(path) or os.lstat(path).st_nlink > 1:   # chmod would reach another file
                raise
            os.chmod(path, 0o666)   # read-only
            os.unlink(path)

    store.retry_permission(remove)


def _empty(folder):
    """Remove everything in the folder. Links are removed themselves and never followed."""
    with os.scandir(folder) as entries:
        paths = [e.path for e in entries]
    for path in paths:
        if not _is_link(path) and os.path.isdir(path):
            try:
                _empty(path)
            except FileNotFoundError:
                continue   # the folder is gone
            try:
                os.rmdir(path)
            except OSError:
                pass   # a terminal stands in it; an empty folder does no harm
        else:
            _remove_file(path)


def _template():
    """{relative path: text} of the fake project, with the checklist."""
    files = {}
    for path in sorted(TEMPLATE.rglob("*")):
        if path.is_file():
            files[path.relative_to(TEMPLATE).as_posix()] = path.read_bytes().decode("utf-8").replace("\r\n", "\n")
    if SETTINGS not in files:
        raise RehearsalError(texts.rehearsal_no_template(TEMPLATE))
    files[CHECKLIST.name] = CHECKLIST.read_bytes().decode("utf-8").replace("\r\n", "\n")
    return files


def _build(project):
    """Make the fake project again. Its project.json comes last, as the sign that it is complete."""
    folder, files = _checked_folder(project), _template()
    settings = files.pop(SETTINGS)
    os.makedirs(folder, exist_ok=True)
    _empty(folder)
    for rel, text in files.items():
        store.write_text(folder / rel, text)
    fake = Project(folder, json.loads(settings))
    merged = []
    for n in fake.phase_numbers():
        data = fake.update_state(n, lambda d: _freshen(fake, d))
        if data.get("status") == "done" and data.get("branch"):
            merged.append(data["branch"])
    store.write(state.sim_path(fake), {"branch": state.phase_branch(fake), "merged": merged})
    store.write_text(folder / SETTINGS, settings)


def _now(fake):
    """A time that no code change is later than."""
    return max(time.time(), scan.last_code_change(fake))


def _freshen(fake, data):
    for entry in data.get("results", {}).values():
        entry["time"] = _now(fake)


# --- the restart ---------------------------------------------------------------------------------------

def _stamp(project):
    """The change time of config.json; None if it has just gone."""
    try:
        return os.stat(project.root / LEARNING / "config.json").st_mtime_ns
    except FileNotFoundError:
        return None


def _run_of(seen):
    run = seen.get("run")
    return run if isinstance(run, int) and not isinstance(run, bool) and run >= 1 else 0


def _is_current(project, seen, stamp):
    folder = project.rehearsal_folder
    return (type(seen.get("mtime")) is int and seen["mtime"] == stamp and _run_of(seen) > 0
            and (folder / LEARNING / "project.json").is_file()
            and not any(_is_link(p) for p in (folder, folder.parent, folder.parent.parent)))   # then it is refused


def _restart(project, seen):
    stamp = _stamp(project)
    if stamp is None or _is_current(project, seen, stamp):   # another chat was faster
        raise _Nothing()
    old = _run_of(seen)
    try:   # each tick saves the report, so only a run without ticks has none yet; a kept one stays as it is
        if old and _record(project, old) and not report_path(project, old).exists():
            _save_report(project, old)
    except Exception:
        pass   # a restart must not fail for it
    _build(project)
    used = _numbers(_local(project) / RUNS) + _numbers(report_path(project, 0).parent)   # also if local/ was deleted
    run = max([old] + used) + 1
    store.write(_local(project) / _record_name(run), {
        "run": run, "started": store.now(), "version": version.VERSION, "hash": version.plugin_hash(), "ticks": {}})
    return {"mtime": stamp, "run": run}


def sync(project):
    """Start the rehearsal again if config.json was saved since the last look, while the switch is on."""
    if not project.rehearsal or project.is_rehearsal:
        return
    if _is_current(project, _seen(project), _stamp(project)):
        return
    try:
        project.update_local(SEEN, lambda seen: _restart(project, seen), tolerant=True)
    except _Nothing:
        pass


# --- the simulation --------------------------------------------------------------------------------------

def _is_done(active, data, script):
    """True for a script without TODOs whose last results passed, also if they are old."""
    fresh = {s: True for s in active.settings.get("suites", [])}
    planned = [str(t) for t in script.get("tests", [])]
    return not scan.todos(active.root / script.get("path", "")) and all(
        state.outcome(active, data, t, fresh) == "passed" for t in planned)


def _simulate_tests(active, good):
    n = commands.latest(active)

    def apply(data):
        if n is None or data.get("status") != "build":
            raise RehearsalError(texts.rehearsal_no_build(n, data.get("status") or "planning"))
        outcomes = {}
        for s in store.read(active.plan_path(n)).get("scripts", []):
            passed = good or _is_done(active, data, s)
            outcomes.update({str(t): "passed" if passed else "failed" for t in s.get("tests", [])})
        stored = data.setdefault("results", {})
        for i, suite in enumerate(active.settings.get("suites", [])):
            tests = (stored.get(suite) or {}).get("tests") or {}
            tests = {k: "passed" for k in tests if not any(results.matches(t, k) for t in outcomes)}
            stored[suite] = {"time": _now(active), "tests": dict(tests, **outcomes) if i == 0 else tests}

    active.update_state(n, apply)


def _simulate_git(active, branch=None, merged=None):
    now = state.sim(active)
    if branch:
        now["branch"] = branch
    if merged and merged not in now["merged"]:
        now["merged"].append(merged)
    store.write(state.sim_path(active), now)


def command(project, args):
    """learning.py rehearse: the simulation, the owner's tick and the report."""
    if not project.rehearsal:
        raise RehearsalError(texts.REHEARSE_OFF)
    word, rest = (args[0] if args else None), list(args[1:])
    wanted = {"check": (1,), "branch": (0, 1)}.get(word, (0,))
    if word not in WORDS or len(rest) not in wanted:
        raise RehearsalError(texts.REHEARSE_USAGE)
    active = project.active
    if word in ("pass", "fail"):
        _simulate_tests(active, word == "pass")
        return texts.SIM_PASS if word == "pass" else texts.SIM_FAIL
    if word == "branch":
        branch = rest[0].strip() if rest and rest[0].strip() else WRONG_BRANCH
        _simulate_git(active, branch=branch)
        return texts.sim_branch(branch)
    if word == "merge":
        branch = state.phase_branch(active)
        if not branch:
            raise RehearsalError(texts.REHEARSAL_NO_BRANCH)
        _simulate_git(active, merged=branch)
        return texts.sim_merged(branch)
    if word == "check":
        if any(c.id == rest[0] and c.by != "owner" for c in checklist()):
            raise RehearsalError(texts.script_ticks(rest[0]))
        tick(project, rest[0], "owner")
        return texts.ticked(rest[0], "owner")
    return report(project) + "\n" + compare(project)


# --- the checklist and the reports --------------------------------------------------------------------------

def checklist():
    """The lines of the table in checklist.md."""
    found = []
    for line in CHECKLIST.read_bytes().decode("utf-8").splitlines():
        cells = [c.strip() for c in line.split("|")[1:-1]]
        if len(cells) == len(Check._fields) and cells[0].startswith("`"):
            found.append(Check(cells[0].strip("`"), *cells[1:]))
    return found


def ticks(project):
    """{check id: its tick} of the run that is going on."""
    return _ticks_of(_record(project, render.run_number(project)))


def tick(project, check_id, by="script", session=None):
    """Tick a check of the run that is going on. True if it was open; the first tick counts."""
    if not project.rehearsal:
        return False
    known = [c.id for c in checklist()]
    if check_id not in known:
        raise RehearsalError(texts.unknown_check(check_id, known))
    run = render.run_number(project)

    def apply(data):
        found = _ticks_of(data)
        if check_id in found:
            raise _Nothing()
        found[check_id] = {"time": store.now(), "by": by, "session": session}
        data["ticks"] = found

    try:
        project.update_local(_record_name(run), apply, after=lambda: _save_report(project, run))
    except _Nothing:
        return False
    return True


def _plugin(record):
    return record.get("version", "?"), record.get("hash", "?")


def report(project, run=None):
    """Which checks of a run are ticked, by whom and when, and which are open."""
    run = run or render.run_number(project)
    record = _record(project, run)
    done, lines = _ticks_of(record), checklist()
    gone = [i for i in sorted(done) if i not in [c.id for c in lines]]
    head = ["# " + texts.report_title(run), "", texts.report_about(record.get("started", "?"), *_plugin(record)),
            texts.report_count(sum(1 for c in lines if c.id in done), len(lines)), ""]
    return "\n".join(head + [texts.report_line(c.id, c.type, done.get(c.id)) for c in lines]
                     + [texts.report_line(i, texts.CHECK_GONE, done[i]) for i in gone]) + "\n"


def compare(project, run=None):
    """How a run differs from the one before it."""
    run = run or render.run_number(project)
    last = max([r for r in _numbers(_local(project) / RUNS) if r < run], default=None)
    if last is None:
        return texts.compare_first(run)
    now, before = _record(project, run), _record(project, last)
    order = [c.id for c in checklist()]
    order += sorted((set(_ticks_of(now)) | set(_ticks_of(before))) - set(order))
    new = [i for i in order if i in _ticks_of(now) and i not in _ticks_of(before)]
    missing = [i for i in order if i in _ticks_of(before) and i not in _ticks_of(now)]
    lines = [texts.compare_heading(run, last)]
    lines += [texts.compare_new(new)] if new else []
    lines += [texts.compare_open(missing)] if missing else []
    lines += [] if new or missing else [texts.COMPARE_SAME]
    same = _plugin(now) == _plugin(before)
    lines.append(texts.COMPARE_PLUGIN_SAME if same
                 else texts.compare_plugin("%s %s" % _plugin(before), "%s %s" % _plugin(now)))
    return "\n".join(lines)


def _save_report(project, run):
    store.write_text(report_path(project, run), report(project, run) + "\n" + compare(project, run) + "\n")


# --- what the script sees --------------------------------------------------------------------------------------

def _in_other_chat(done, check_id, session):
    """True if the check was ticked in a chat that is not this one."""
    before = done.get(check_id, {}).get("session")
    return bool(session and before and before != session)


def _start_checks(active, n, rest, data, ok, done, session):
    before = store.read(active.state_path(n - 1))
    status = (before.get("status") or "planning") if before else None
    if ok and rest:
        return ["start-skip"] if status == "skipped" else []
    if ok:
        return ["start-new-chat"] if _in_other_chat(done, "finish", session) else []
    if rest or data:
        return []
    return {"done": ["start-unmerged"], "planning": ["start-early"], "build": ["start-early"]}.get(status, [])


def _build_checks(active, n, data, ok):
    st = state.compute(active, n)
    if ok:
        part = data.get("part", 0)
        tasks = len(store.read(active.plan_path(n))["parts"][part]["tasks"])
        finished = sum(1 for t in data.get("tasksDone", []) if t.get("part") == part)
        return ["build-resumed"] if 0 < finished < tasks else []
    if data and st.status == "planning":
        return ["build-unapproved"]
    return ["build-owners-turn"] if st.status == "build" and st.turn == "owner" and not st.wrong_branch else []


def _summarize_checks(active, n, ok, done, session):
    st = state.compute(active, n)
    if not ok:
        return []
    if st.wrong_branch:
        return ["wrong-branch"]
    if st.status != "build":
        return []
    found = []
    if st.turn == "owner" and (st.todos_done, st.todos_total) == (2, 5):
        found += ["resume-closed"] if _in_other_chat(done, "resume-half", session) else []
        found.append("resume-half")
    if any(s.handed and s.failing and not s.todos_left for s in st.scripts):
        found.append("todo-failing")
    return found


def _finish_checks(active, n, data, ok):
    if ok:   # pending: closed just now, and not a phase that was done already
        return ["finish"] if (data.get("closing") or {}).get("pending") else []
    return ["finish-early"] if data.get("status") == "build" and not state.compute(active, n).wrong_branch else []


def _command_checks(active, name, argument, ok, done, session):
    """The checks of the checklist that the outcome of a command shows."""
    n, rest = commands.split_argument(argument)
    n = commands.latest(active) if n is None else n
    if not n:
        return []
    data = store.read(active.state_path(n))
    if name == "start-phase":
        return _start_checks(active, n, rest, data, ok, done, session)
    if name == "build-phase":
        return _build_checks(active, n, data, ok)
    if name == "summarize-phase":
        return _summarize_checks(active, n, ok, done, session)
    return _finish_checks(active, n, data, ok) if name == "finish-phase" else []


def _warned(action):
    """Do what must never stop a command; the lines of a warning if it failed."""
    try:
        action()
    except Exception as e:
        return [texts.tick_failed(e)]
    return []


def note(project, check_id, session=None):
    """Tick a check that the script saw. Never fails: returns the lines of a warning."""
    return _warned(lambda: tick(project, check_id, session=session))


def _note_command(project, name, argument, ok, session):
    def action():
        for check_id in _command_checks(project.active, name, argument, ok, ticks(project), session):
            tick(project, check_id, session=session)

    return _warned(action)


def rules(project):
    """What the AI must know in a rehearsal."""
    return texts.rehearsal_rules(render.run_number(project), (version.ROOT / "scripts" / "run.sh").as_posix())


def run(project, name, argument="", watch=True, session=None):
    """commands.run. In a rehearsal its text says so, and what the script sees is ticked (watch)."""
    out = commands.run(project, name, argument)
    if not project.rehearsal:
        return out
    lines = [rules(project) if out.ok and name in WITH_RULES
             else texts.rehearsal_short(render.run_number(project))]
    if watch:
        lines += _note_command(project, name, argument, out.ok, session)
    if out.ok and name == "summarize-phase":
        shown = []
        failed = _warned(lambda: shown.append(compare(project)))
        lines += shown + failed
    return out._replace(text="\n".join(lines + [out.text]))


def hand_over(project, n=None):
    """commands.hand_over, ticked in a rehearsal."""
    out = commands.hand_over(project, n)
    if not project.rehearsal:
        return out

    def action():
        active = project.active
        number = commands.latest(active) if n is None else n
        if out.ok:
            tick(project, "hand-over")
        elif number and state.compute(active, number).lost_todos:
            tick(project, "hand-over-missing")

    return out._replace(text="\n".join(_warned(action) + [out.text]))
