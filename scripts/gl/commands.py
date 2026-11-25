"""The owner's commands and the hand-over of the AI. Decisions are made inside store.update, so two
chats at once cannot both act on the same old state."""
import math
import re
from collections import namedtuple

from . import render, results, scan, state, store, texts, version

Outcome = namedtuple("Outcome", "ok text")

_PROMPT = re.compile(r"\s*/(?:guided-learning:)?([a-z-]+)(?:\s+(.*))?$", re.S)
_NUMBER = re.compile(r"(?:phase[- ]?)?([0-9]{1,6})(?:\s+(.*))?$", re.I | re.S)


class _Stop(Exception):
    """Leaves a store.update callback without writing anything."""

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
    return max(project.phase_numbers(), default=None)


def _suggestion(project):
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
    startable = n if n == 1 or n - 1 in known else max(known, default=0) + 1
    raise _refuse([texts.no_phase(n, known)], texts.next_line("start-phase", startable))


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

    store.update(project.state_path(prev), apply)


def _add(items, more):
    items.extend(i for i in more if i not in items)


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
            raise _refuse([texts.previous_not_merged(n, st.branch)], texts.next_line("start-phase", n))
    elif st.status != "skipped":
        items = ([texts.wrong_branch(st.branch, st.wrong_branch)] if st.wrong_branch else []) + st.open_items
        raise _refuse([texts.previous_open(n)] + _open_lines(items), render.next_line(st))
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
                raise _Stop(True, _planning_lines(project, n, data), render.next_line(st))
            raise _refuse([texts.already_started(n, st.status)], render.next_line(st))
        _add(carried, data.get("carried") or [])
        _leave_previous(project, n, reason, carried)
        _create_files(project, n)
        for key in ("skip", "turn", "part", "planHash", "branch", "locked", "tasksDone"):
            data.pop(key, None)   # left over if the phase was skipped before
        data["status"] = "planning"
        if carried:
            data["carried"] = list(carried)

    data = store.update(path, apply)
    return Outcome(True, "\n".join(_planning_lines(project, n, data) + [texts.next_line("approve-phase", n)]))


def _planning_lines(project, n, data):
    lines = [texts.planning_started(n, _docs_path(project, project.plan_path(n)),
                                    _docs_path(project, project.md_path(n)))]
    carried = data.get("carried") or []
    if carried:
        lines += [texts.CARRIED_HEADING] + [texts.bullet(c) for c in carried]
    return lines


# --- approve: the check of the plan ----------------------------------------------------------

def _filled(value):
    return isinstance(value, str) and bool(value.strip())


def _filled_list(value):
    """True for a list of texts with at least one entry."""
    return isinstance(value, list) and bool(value) and all(_filled(v) for v in value)


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _entries(plan, key, gaps):
    """The objects in a list of the plan; gaps for a wrong type and for missing or repeated ids."""
    items = plan.get(key, [])
    if not isinstance(items, list) or not all(isinstance(i, dict) for i in items):
        gaps.append(texts.gap_list(key))
        return []
    if key != "parts":
        ids = [str(i["id"]) for i in items if i.get("id") not in (None, "")]
        if len(ids) < len(items):
            gaps.append(texts.gap_id(key))
        gaps += [texts.gap_duplicate(key, i) for i in _repeated(ids)]
    return items


def _repeated(ids):
    return sorted({i for i in ids if ids.count(i) > 1})


def _part_scripts(part):
    ids = part.get("scripts")
    return [str(i) for i in ids] if isinstance(ids, list) else []


def _script_gaps(scripts, concepts, parts):
    gaps = []
    if not 1 <= len(scripts) <= 5:
        gaps.append(texts.gap_script_count(len(scripts)))
    known = {str(c.get("id")) for c in concepts}
    placed = [i for p in parts for i in _part_scripts(p)]
    for s in scripts:
        sid = str(s.get("id"))
        label = texts.script_label(sid, s.get("name", ""))
        if not re.fullmatch("[0-9]+", sid) and s.get("id") not in (None, ""):
            gaps.append(texts.gap_script_id(sid))
        for key in ("path", "concept"):
            if not _filled(s.get(key)):
                gaps.append(texts.gap_script(label, key))
        for key in ("todos", "tests"):
            if not _filled_list(s.get(key)):
                gaps.append(texts.gap_script(label, key))
        if _filled(s.get("concept")) and s["concept"] not in known:
            gaps.append(texts.gap_unknown_concept(label, s["concept"]))
        todos = s["todos"] if _filled_list(s.get("todos")) else []
        gaps += [texts.gap_todo(label, t) for t in todos if not re.fullmatch(re.escape(sid) + r"\.[0-9]+", t)]
        gaps += [texts.gap_duplicate("TODOs", t) for t in _repeated(todos)]
        if placed.count(sid) != 1:
            gaps.append(texts.gap_parts(label, placed.count(sid)))
    return gaps


def _part_gaps(parts, scripts):
    gaps = [] if parts else [texts.GAP_NO_PART]
    known = {str(s.get("id")) for s in scripts}
    for i, p in enumerate(parts):
        label = texts.part_label(i, p.get("name", ""))
        if not _filled_list(p.get("tasks")):
            gaps.append(texts.gap_part_tasks(label))
        if not isinstance(p.get("scripts", []), list):
            gaps.append(texts.gap_part_scripts(label))
        gaps += [texts.gap_part_script(label, sid) for sid in _part_scripts(p) if sid not in known]
    return gaps


def _target_gaps(targets):
    gaps = [] if targets else [texts.GAP_NO_TARGET]
    for t in targets:
        low, high = t.get("min"), t.get("max")
        given = [v for v in (low, high) if v is not None]
        if not _filled(t.get("measure")):
            gaps.append(texts.gap_target(t.get("id"), "measure"))
        if not _filled_list(t.get("settings")):
            gaps.append(texts.gap_target(t.get("id"), "settings"))
        if not given or not all(_number(v) for v in given) or (len(given) == 2 and low > high):
            gaps.append(texts.gap_target_range(t.get("id")))
    return gaps


def plan_gaps(project, n):
    """Everything that keeps the plan of phase n from being approved."""
    plan, gaps = store.read(project.plan_path(n)), []
    concepts, parts, scripts, targets, questions = [
        _entries(plan, k, gaps) for k in ("concepts", "parts", "scripts", "targets", "questions")]
    if not concepts:
        gaps.append(texts.GAP_NO_CONCEPT)
    gaps += [texts.gap_concept_name(c.get("id")) for c in concepts if not _filled(c.get("name"))]
    gaps += _script_gaps(scripts, concepts, parts) + _part_gaps(parts, scripts) + _target_gaps(targets)
    asked = {str(q.get("concept")) for q in questions}
    gaps += [texts.gap_question(c.get("name") or c.get("id")) for c in concepts if str(c.get("id")) not in asked]
    gaps += [texts.gap_points(q.get("id")) for q in questions if not _filled_list(q.get("points"))]
    return gaps


def _gap_stop(project, n, gaps):
    name = project.plan_path(n).name
    return _refuse([texts.plan_incomplete(name)] + [texts.bullet(g) for g in gaps], texts.next_line("approve-phase", n))


# --- approve -----------------------------------------------------------------------------------

def _branch(project):
    """The branch to store: None on a detached HEAD or without git."""
    current = state.current_branch(project)
    return None if current == state.DETACHED else current


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
        raise _gap_stop(project, n, gaps)
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
                raise _gap_stop(project, n, gaps)
            data.update(status="build", planHash=store.file_hash(project.plan_path(n)), branch=_branch(project))
            count = len(store.read(project.plan_path(n))["scripts"])
            lines[:] = [texts.approved(n)] + ([texts.few_scripts_note(count)] if count < 3 else [])
        else:
            st = state.compute(project, n)
            raise _refuse([texts.cannot_in_status("approve-phase", n, status)], render.next_line(st))

    store.update(project.state_path(n), apply)
    return Outcome(True, "\n".join(lines + [render.next_line(state.compute(project, n))]))


# --- build -------------------------------------------------------------------------------------

def _wrong_branch(st):
    if st.wrong_branch:
        raise _refuse([texts.wrong_branch(st.branch, st.wrong_branch)], render.next_line(st))


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

    data = store.update(project.state_path(n), apply)
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
    ids = {i for p in part_indexes for i in _part_scripts(_part(plan, p))}
    return [s for s in plan.get("scripts", []) if str(s.get("id")) in ids]


def _label(script):
    return texts.script_label(script.get("id"), script.get("name", ""))


def _todo_misses(project, scripts):
    return [texts.todo_not_in_shell(_label(s), t, s["path"]) for s in scripts
            for t in s.get("todos", []) if t not in scan.todos(project.root / s["path"])]


def _test_code_misses(project, scripts):
    codes = [text for _, text in scan.texts(project)]

    def in_code(test):
        words = test.split("(", 1)[0].split(".")[-2:]   # class and method
        return any(all(re.search(r"\b%s\b" % re.escape(w), code) for w in words) for code in codes)

    return [texts.test_not_in_code(_label(s), t) for s in scripts for t in s.get("tests", []) if not in_code(t)]


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
        data.update(locked=locked, turn="owner")

    try:
        if n is None:
            raise _refuse([texts.NO_PHASE_YET], texts.next_line("start-phase", 1))
        _need_phase(project, n)
        data = store.update(project.state_path(n), apply)
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
    lines += [texts.closing_carried(n + 1, weak, differently),
              texts.next_in_new_chat("start-phase", n + 1, "" if merged else texts.MERGE_FIRST)]
    return "\n".join(lines)


def _finish(project, n, rest):
    _no_rest("finish-phase", n, rest)
    _need_phase(project, n)

    def apply(data):
        st = state.compute(project, n)
        if st.status == "done":
            raise _Stop(True, [texts.done_text(n)], render.next_line(st))
        if st.status == "skipped":
            raise _refuse([texts.skipped_text(n, st.skip_reason)], render.next_line(st))
        _wrong_branch(st)
        if st.open_items or st.status != "wrap-up":
            raise _refuse([texts.not_finished(n)] + _open_lines(st.open_items or [texts.still_in(st.status)]),
                          render.next_line(st))
        data.update(status="done", locked=[], closing={"pending": True, "tries": 0})

    store.update(project.state_path(n), apply)
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
        raise _refuse([texts.bad_number(argument.strip(), name)], _suggestion(project))
    return _COMMANDS[name](project, n, rest)


def run(project, name, argument=""):
    """Run one of the five commands of a phase; `name` with or without "-phase"."""
    project = project.active
    name = name if name in _COMMANDS else name + "-phase"
    try:
        return _run(project, name, argument or "")
    except _Stop as stop:
        return stop.outcome
