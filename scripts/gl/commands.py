"""The owner's commands and the hand-over of the AI. Decisions are made inside update_state, so two
chats at once cannot both act on the same old state."""
import re
from collections import namedtuple

from . import render, results, scan, scorecard, state, store, texts, version
from .plan import part_scripts, plan_gaps
from .project import norm

Outcome = namedtuple("Outcome", "ok text")

_PROMPT = re.compile(r"\s*/(?:guided-learning:)?([a-z-]+)(?:\s+(.*))?$", re.S)
_NUMBER = re.compile(r"(?:phase[- ]?)?([0-9]{1,6})(?:\s+(.*))?$", re.I | re.S)


class _Stop(Exception):
    """Leaves an update_state callback without writing anything."""

    def __init__(self, ok, lines, next_line):
        super().__init__(next_line)
        self.outcome = Outcome(ok, "\n".join(list(lines) + [next_line]))


def _refuse(lines, next_line):
    return _Stop(False, lines, next_line)


# --- arguments -----------------------------------------------------------------------------

def parse(prompt):
    """(command, argument) of a typed command of this plugin, or None for any other prompt."""
    m = _PROMPT.match(prompt or "")
    if not m or m.group(1) not in texts.COMMANDS:
        return None
    return m.group(1), (m.group(2) or "").strip()


def split_argument(argument):
    """(phase number, rest) of "2", "phase-2" or "2 skip: x"; (None, text) if there is no number."""
    text = (argument or "").strip()
    m = _NUMBER.match(text)
    if not m:
        return None, text
    return int(m.group(1)), (m.group(2) or "").strip()


def _keyword(rest, word):
    """The text after "word:", "" for "word" or "word:" alone, or None if rest is something else."""
    m = re.match(word + r"\s*(?::\s*(.*))?$", rest, re.I | re.S)
    return (m.group(1) or "").strip() if m else None


def latest(project):
    away = [n for n in project.open_phases() if state.open_elsewhere(project, n)]
    away += [n for n in project.done_phases() if state.done_elsewhere(project, n)]
    return max(project.phase_numbers() + away, default=None)


def suggestion(project):
    """The next line that fits the project as a whole."""
    n = latest(project)
    return texts.next_line("start-phase", 1) if n is None else render.next_line(state.compute(project, n))


def _docs_path(project, path):
    """A phase file as the owner knows it: the docs folder of project.json and the file name."""
    return "%s/%s" % (project.settings.get("docs", "").rstrip("/"), path.name)


def _need_phase(project, n):
    """Refuse a phase that has no state file."""
    if project.state_path(n).exists():
        return
    known = project.phase_numbers()
    last = latest(project)
    if last is not None and state.done_elsewhere(project, last):   # nothing can start before the merge
        raise _refuse([texts.no_phase(n, known)], suggestion(project))
    startable = n if n == 1 or n - 1 in known else max(known, default=0) + 1
    raise _refuse([texts.no_phase(n, known)], texts.next_line("start-phase", startable))


def _refuse_elsewhere(project, name, n):
    """Refuse a command of a phase that is open, or done and not merged, on another branch; a later one
    cannot start either."""
    def concerned(number):
        return number == n or name == "start-phase" and number < n

    for number in sorted(project.open_phases()):
        if concerned(number) and state.open_elsewhere(project, number):
            _wrong_branch(state.compute(project, number))
    for number in sorted(project.done_phases(), reverse=True):   # the latest branch may hold the ones before
        branch = state.done_elsewhere(project, number) if concerned(number) else None
        if branch:
            st = state.compute(project, number)
            raise _refuse([texts.done_not_merged(number, branch, st.following)], render.next_line(st))


def _no_rest(name, n, rest):
    if rest:
        raise _refuse([texts.usage(name)], texts.next_line(name, n))


# --- start -----------------------------------------------------------------------------------

def _skeleton(n):
    return {"phase": n, "concepts": [], "parts": [], "scripts": [], "targets": [], "questions": []}


def _create_files(project, n):
    if not project.plan_path(n).exists():
        store.write(project.plan_path(n), _skeleton(n))
    if not project.md_path(n).exists():
        template = (version.ROOT / "templates" / "phase.md").read_text(encoding="utf-8")
        store.write_text(project.md_path(n), template.replace("{n}", str(n)))


def _carried_lines(project, n):
    weak, differently = state.carry_over(project, n)
    return [texts.carried_concept(c) for c in weak] + ([texts.carried_differently(differently)] if differently else [])


def _mark_skipped(project, prev, reason, items):
    """Mark the previous phase as skipped and add its open items. A done or skipped one stays."""
    def apply(data):
        if data.get("status") not in ("done", "skipped"):
            if data:
                _add(items, state.compute(project, prev).open_items)
            data.update(status="skipped", skip=reason)

    data = project.update_state(prev, apply)
    if data.get("status") == "skipped" or prev in project.open_phases():
        project.note_open(prev, {})   # the record that a phase is done and not merged stays


def _add(items, more):
    items.extend(i for i in more if i not in items)


def _uncommitted_lines(project, n):
    names = state.uncommitted(project, n)
    return [texts.phase_files_uncommitted(n, names)] if names else []


def _leave_previous(project, n, reason, carried):
    """Check the phase before n (or skip it), and add to `carried` what it carries over."""
    if n == 1:
        return
    prev = n - 1
    if reason:
        _mark_skipped(project, prev, reason, carried)
        _add(carried, _carried_lines(project, prev))
        return
    if not project.state_path(prev).exists():
        raise _refuse([texts.previous_missing(n)], texts.next_line("start-phase", n))
    st = state.compute(project, prev)
    if st.status == "done":
        if st.branch and not state.is_merged(project, st.branch):
            raise _refuse([texts.previous_not_merged(n, st.branch)] + _uncommitted_lines(project, prev),
                          texts.next_line("start-phase", n))
    elif st.status != "skipped":
        items = ([_wrong_branch_text(st)] if st.wrong_branch else []) + st.open_items
        raise _refuse([texts.previous_open(n)] + _uncommitted_lines(project, prev) + _open_lines(items),
                      render.next_line(st))
    _add(carried, _carried_lines(project, prev))


def _start(project, n, rest):
    reason = _keyword(rest, "skip")
    if rest and reason is None:
        raise _refuse([texts.usage("start-phase")], texts.next_line("start-phase", n))
    if rest and not reason:
        raise _refuse([texts.skip_needs_reason(n)], texts.next_line("start-phase", n))
    path = project.state_path(n)
    carried = []   # outside of apply, so that a repeated apply still has the items of a skipped phase

    def apply(data):
        if path.exists() and data.get("status") != "skipped":
            st = state.compute(project, n)
            if st.status == "planning":
                raise _Stop(True, _planning_lines(project, n, data), texts.next_line("approve-phase", n))
            raise _refuse([texts.already_started(n, st.status)], render.next_line(st))
        _add(carried, data.get("carried") or [])
        _leave_previous(project, n, reason, carried)
        _create_files(project, n)
        for key in ("skip", "turn", "part", "planHash", "branch", "locked", "handed", "tasksDone"):
            data.pop(key, None)   # left over if the phase was skipped before
        data["status"] = "planning"
        if carried:
            data["carried"] = list(carried)

    data = project.update_state(n, apply)
    project.note_open(n, data)
    before = store.read(project.state_path(n - 1)) if reason else {}
    lines = [texts.skipped_text(n - 1, before.get("skip"))] if before.get("status") == "skipped" else []
    lines += _planning_lines(project, n, data)
    return Outcome(True, "\n".join(lines + [texts.next_line("approve-phase", n)]))


def _planning_lines(project, n, data):
    if project.is_rehearsal:
        lines = [texts.rehearsal_planning(n)]
    else:
        lines = [texts.planning_started(n, _docs_path(project, project.plan_path(n)),
                                        _docs_path(project, project.md_path(n)))]
    carried = data.get("carried") or []
    if carried:
        lines += [texts.CARRIED_HEADING] + [texts.bullet(c) for c in carried]
    return lines


# --- approve: the refusal of an incomplete plan -----------------------------------------------

def _gap_stop(project, n, gaps, command):
    name = project.plan_path(n).name
    return _refuse([texts.plan_incomplete(name)] + [texts.bullet(g) for g in gaps], texts.next_line(command, n))


# --- approve -----------------------------------------------------------------------------------

def _branch(project):
    """The branch to store: None on a detached HEAD or without git."""
    current = state.current_branch(project)
    return None if current == state.DETACHED else current


def _handed_changes(project, data, plan):
    """What a changed plan changes in the scripts and TODOs of the parts that are handed over."""
    before = data.get("handed")
    if not isinstance(before, dict):
        return []
    count = data.get("part", 0) + (1 if data.get("turn") == "owner" else 0)
    now = {str(s.get("id")): s for s in _scripts_of(plan, range(count))}
    items = [texts.handed_added(_label(s)) for i, s in now.items() if i not in before]
    for i, old in before.items():
        s, label = now.get(i), texts.script_label(i, old.get("name", ""))
        if s is None:
            items.append(texts.handed_removed(label))
            continue
        if norm(project.root / s["path"]) != norm(project.root / old.get("path", "")):
            items.append(texts.handed_path(label, old.get("path", ""), s["path"]))
        todos = old.get("todos", [])
        items += [texts.handed_todo_added(label, t) for t in s["todos"] if t not in todos]
        items += [texts.handed_todo_removed(label, t) for t in todos if t not in s["todos"]]
    return items


def _accept_change(project, n, data, reason):
    """Record a changed plan (reason None: the owner did not type change:)."""
    path = project.plan_path(n)
    here = texts.next_line("approve-phase", n)
    if not state.plan_differs(project, n, data):
        if reason is None:
            raise _Stop(True, [texts.approved_already(n)], render.next_line(state.compute(project, n)))
        raise _refuse([texts.nothing_changed(n)], render.next_line(state.compute(project, n)))
    if reason is None:
        raise _refuse([texts.plan_changed(n, path.name)], here)
    if not reason:
        raise _refuse([texts.change_needs_reason(n)], here)
    gaps = plan_gaps(project, n)
    if gaps:
        raise _gap_stop(project, n, gaps, "approve-phase")
    changed = _handed_changes(project, data, store.read(path))
    if changed:
        raise _refuse([texts.handed_changed(n)] + [texts.bullet(c) for c in changed], here)
    new = store.file_hash(path)
    data.setdefault("changes", []).append({"time": store.now(), "reason": reason,
                                           "from": data.get("planHash"), "to": new})
    data["planHash"] = new


def _approve(project, n, rest):
    reason = _keyword(rest, "change") if rest else None
    if rest and reason is None:
        _no_rest("approve-phase", n, rest)
    _need_phase(project, n)
    lines = []

    def apply(data):
        status = data.get("status") or "planning"
        if status == "build":
            _accept_change(project, n, data, reason)
            lines[:] = [texts.change_accepted(n)]
        elif status == "planning":
            gaps = plan_gaps(project, n)
            if gaps:
                raise _gap_stop(project, n, gaps, "start-phase")   # planning goes on
            data.update(status="build", planHash=store.file_hash(project.plan_path(n)), branch=_branch(project))
            count = len(store.read(project.plan_path(n))["scripts"])
            lines[:] = [texts.approved(n)] + ([texts.few_scripts_note(count)] if count < 3 else [])
        else:
            st = state.compute(project, n)
            raise _refuse([texts.cannot_in_status("approve-phase", n, status)], render.next_line(st))

    project.note_open(n, project.update_state(n, apply))
    return Outcome(True, "\n".join(lines + [render.next_line(state.compute(project, n))]))


# --- build -------------------------------------------------------------------------------------

def _wrong_branch_text(st):
    return texts.wrong_branch(st.branch, st.wrong_branch, st.project.is_rehearsal)


def _wrong_branch(st):
    if st.wrong_branch:
        raise _refuse([_wrong_branch_text(st)], render.next_line(st))


def _open_lines(items):
    return [texts.open_heading()] + [texts.bullet(i) for i in items]


def _not_buildable(project, n, status):
    """The refusal of build for a phase that is not in status build."""
    st = state.compute(project, n)
    if status != "planning":
        return _refuse([texts.cannot_in_status("build-phase", n, status)], render.next_line(st))
    gaps = plan_gaps(project, n)
    more = [texts.plan_incomplete(project.plan_path(n).name)] + [texts.bullet(g) for g in gaps] if gaps else []
    return _refuse([texts.plan_not_approved(n)] + more, render.next_line(st))


def _build(project, n, rest):
    _no_rest("build-phase", n, rest)
    _need_phase(project, n)

    def apply(data):
        status = data.get("status") or "planning"
        if status != "build":
            raise _not_buildable(project, n, status)
        st = state.compute(project, n)
        if not data.get("turn"):
            data["branch"] = _branch(project)   # the first build decides the branch
        else:
            _wrong_branch(st)
        if not st.parts_total:
            raise _refuse(st.problems, render.next_line(st))
        if st.status != "build":
            raise _refuse([texts.build_is_over(n, st.status)], render.next_line(st))
        if st.turn == "owner":
            items = [i for s in st.scripts if s.handed for i in s.open_items()]
            raise _refuse([texts.owners_turn(n, st.part)] + _open_lines(items), render.next_line(st))
        data.update(turn="ai", part=st.part)

    data = project.update_state(n, apply)
    project.note_open(n, data)
    return Outcome(True, "\n".join(_build_lines(project, n, data) + [texts.next_line("summarize-phase", n)]))


def _build_lines(project, n, data):
    st = state.compute(project, n)
    plan = store.read(project.plan_path(n))
    done = data.get("tasksDone") or []
    lines = st.problems + [texts.build_heading(n, st.part, st.parts_total, st.part_name)]
    for i, task in enumerate(_part(plan, st.part).get("tasks", [])):
        lines.append(texts.task_line(i, task, {"part": st.part, "index": i} in done))
    lines.append(texts.SCRIPTS_HEADING)
    for s in _scripts_of(plan, [st.part]):
        lines.append(texts.script_line(_label(s), s.get("path", ""), s.get("todos", []), s.get("tests", [])))
    return lines + [texts.build_rules(n, st.part)]


# --- hand-over -----------------------------------------------------------------------------------

def _part(plan, index):
    parts = plan.get("parts") or []
    return parts[index] if index < len(parts) else {}


def _scripts_of(plan, part_indexes):
    ids = {i for p in part_indexes for i in part_scripts(_part(plan, p))}
    return [s for s in plan.get("scripts", []) if str(s.get("id")) in ids]


def _label(script):
    return texts.script_label(script.get("id"), script.get("name", ""))


def _todo_misses(project, scripts):
    return [texts.todo_not_in_shell(_label(s), t, s["path"]) for s in scripts
            for t in s.get("todos", []) if t not in scan.todos(project.root / s["path"])]


def _test_code_misses(project, scripts):
    codes = [text for _, text in scan.texts(project)]
    return [texts.test_not_in_code(_label(s), t) for s in scripts for t in s.get("tests", [])
            if not any(scan.has_test(code, t) for code in codes)]


def _owner_test_misses(project, data, scripts):
    fresh = [data["results"][s].get("tests", {}) for s in project.settings.get("suites", [])
             if results.fresh(project, data, s)]
    items = []
    for s in scripts:
        for t in s.get("tests", []):
            hits = [o for tests in fresh for name, o in tests.items() if results.matches(t, name)]
            if not hits:
                items.append(texts.owner_test_not_run(_label(s), t))
            elif "passed" in hits:
                items.append(texts.owner_test_passes(_label(s), t))
    return items


def _hand_over_misses(project, data, plan, part):
    scripts = _scripts_of(plan, [part])
    later = [t for s in _scripts_of(plan, range(part, len(plan.get("parts") or []))) for t in s.get("tests", [])]
    return (_todo_misses(project, scripts) + _test_code_misses(project, scripts)
            + _owner_test_misses(project, data, scripts)
            + state.suite_items(project, data, leave_out=later))


def _hand_over_check(project, n, data):
    """Refuse a hand-over, or return the scripts that are handed over."""
    st = state.compute(project, n)
    if data.get("status") != "build" or data.get("turn") != "ai":
        raise _refuse([texts.no_hand_over(n)], render.next_line(st))
    _wrong_branch(st)
    plan = store.read(project.plan_path(n))
    if not st.parts_total or not _part(plan, data.get("part", 0)):
        raise _refuse([texts.plan_missing(project.plan_path(n).name)], render.next_line(st))
    misses = _hand_over_misses(project, data, plan, data.get("part", 0))
    if misses:
        raise _refuse([texts.hand_over_refused(n, data.get("part", 0))] + [texts.bullet(m) for m in misses],
                      render.next_line(st))
    return _scripts_of(plan, [data.get("part", 0)])


def hand_over(project, n=None):
    """The AI hands its part over to the owner; n None means the latest phase."""
    project = project.active
    n = latest(project) if n is None else n
    done = []

    def apply(data):
        done[:] = _hand_over_check(project, n, data)
        locked = list(data.get("locked") or [])
        _add(locked, [s["path"] for s in done])
        handed = dict(data.get("handed") or {})
        handed.update({str(s["id"]): {k: s.get(k) for k in ("name", "path", "todos")} for s in done})
        data.update(locked=locked, handed=handed, turn="owner")

    try:
        if n is None:
            raise _refuse([texts.NO_PHASE_YET], texts.next_line("start-phase", 1))
        _refuse_elsewhere(project, "hand-over", n)
        _need_phase(project, n)
        data = project.update_state(n, apply)
        project.note_open(n, data)
    except _Stop as stop:
        return stop.outcome
    st = state.compute(project, n)
    todos = sum(len(s.get("todos", [])) for s in done)
    next_line = texts.next_in_new_chat("summarize-phase", n)
    if render.next_command(st)[0] == "build-phase":
        next_line = render.next_line(st)
    return Outcome(True, texts.handed_over(n, data.get("part", 0), len(done), todos) + "\n" + next_line)


# --- summarize and finish --------------------------------------------------------------------------

def _summarize(project, n, rest):
    _no_rest("summarize-phase", n, rest)
    if not state.open_elsewhere(project, n) and not state.done_elsewhere(project, n):
        _need_phase(project, n)
    return Outcome(True, render.status(state.compute(project, n)).rstrip("\n"))


def closing_text(project, n):
    """The text printed once when phase n is done. Worked out from the stored state, the phase
    files and the merge status, so a later call gives the same text."""
    branch = store.read(project.state_path(n)).get("branch")
    merged = not branch or state.is_merged(project, branch)
    weak, differently = state.carry_over(project, n)
    lines = [texts.closing_done(n, _docs_path(project, project.md_path(n)))]
    if branch:
        lines.append(texts.closing_branch(branch, merged))
    in_git = bool(branch) or state.current_branch(project) is not None   # else there is nothing to commit to
    lines += [texts.closing_carried(n + 1, weak, differently),
              texts.next_in_new_chat("start-phase", n + 1, texts.closing_first(in_git, not merged))]
    return "\n".join(lines)


def _finish(project, n, rest):
    _no_rest("finish-phase", n, rest)
    _need_phase(project, n)

    def apply(data):
        st = state.compute(project, n)
        if st.status == "done":
            scorecard.write_once(project, n)   # nothing changes if it is there; mends a write that was cut off
            raise _Stop(True, [texts.done_text(n)], render.next_line(st))
        if st.status == "skipped":
            raise _refuse([texts.skipped_text(n, st.skip_reason)], render.next_line(st))
        _wrong_branch(st)
        if st.open_items or st.status != "wrap-up":
            raise _refuse([texts.not_finished(n)] + _open_lines(st.open_items or [texts.still_in(st.status)]),
                          render.next_line(st))
        data.update(status="done", locked=[], closing={"pending": True, "tries": 0})

    project.note_open(n, project.update_state(n, apply))
    scorecard.write_once(project, n)
    return Outcome(True, closing_text(project, n))


# --- dispatch --------------------------------------------------------------------------------

_COMMANDS = {"start-phase": _start, "approve-phase": _approve, "build-phase": _build,
             "summarize-phase": _summarize, "finish-phase": _finish}
_LATEST = ("build-phase", "summarize-phase")   # [N]: without a number, the latest phase


def _run(project, name, argument):
    n, rest = split_argument(argument)
    if n is None and not rest and name in _LATEST:
        n = latest(project)
        if n is None:
            raise _refuse([texts.NO_PHASE_YET], texts.next_line("start-phase", 1))
    if n is None or n < 1:
        raise _refuse([texts.bad_number(argument.strip(), name)], suggestion(project))
    if name != "summarize-phase":   # it shows the wrong branch itself
        _refuse_elsewhere(project, name, n)
    return _COMMANDS[name](project, n, rest)


def run(project, name, argument=""):
    """Run one of the five commands of a phase; `name` with or without "-phase"."""
    project = project.active
    name = name if name in _COMMANDS else name + "-phase"
    try:
        return _run(project, name, argument or "")
    except _Stop as stop:
        return stop.outcome
