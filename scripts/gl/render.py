"""Turn a PhaseState into the text the owner reads."""
from . import markdown, scorecard, store, texts, version


def _rows(st):
    """Table rows: (label, status cell, tests cell, extra)."""
    rows = []
    for s in st.scripts:
        status, tests, extra = texts.STATUS[s.status], "", []
        if s.status == "in progress" and s.todos_left:
            status = texts.todos_of(s.todos_done, s.todos_total)
        if s.status != "not started" and s.tests_total:
            tests = texts.tests_cell(s.tests_passed, s.tests_total)
        if s.status == "unknown":
            extra.append(texts.WHY[s.why])
        if s.failing and not s.todos_left:
            extra.append(texts.failing_note(s.failing))
        if s.help:
            extra.append(texts.help_note(s.help))
        if st.next_todo and s.id == st.next_script:
            extra.append(texts.next_note(st.next_todo))
        rows.append((s.label, status, tests, "   ".join(extra)))
    return rows


def _table(st, header_right):
    rows = _rows(st)
    w0 = max([len(r[0]) for r in rows] or [0])
    w1 = max([len(r[1]) for r in rows] or [0])
    w2 = max([len(r[2]) for r in rows] or [0])
    head = texts.phase_header(st.n, st.status)
    lines = [(head.ljust(max(2 + w0 + 2, len(head) + 2)) + header_right).rstrip() if rows else head]
    for label, status, tests, extra in rows:
        line = "  " + label.ljust(w0) + "  " + status.ljust(w1) + "  " + tests.ljust(w2) + "  " + extra
        lines.append(line.rstrip())
    return lines


def _then(st):
    steps = []
    if st.status == "build":
        steps.append(texts.tune_step(st.targets_met, st.targets_total))
    if st.status in ("build", "tune"):
        steps.append(texts.WRAP_UP)
    return [texts.then_line(steps)] if steps else []


def next_command(st):
    """(command, phase number) that goes on with the phase."""
    n = st.n
    if st.status == "planning":
        return ("start-phase" if st.plan_gaps else "approve-phase"), n
    if st.status in ("done", "skipped"):
        return "start-phase", n + 1
    if st.status == "build":
        return ("build-phase" if st.parts_total and st.turn == "ai" else "summarize-phase"), n
    if st.status == "wrap-up" and not st.open_items:
        return "finish-phase", n
    if st.status == "wrap-up" and st.plan_changed and len(st.open_items) == 1:
        return "approve-phase", n
    return "summarize-phase", n


def next_line(st):
    return texts.next_line(*next_command(st))


def _kept(st):
    """The concept summary and the lessons the owner wrote, for a done phase."""
    md = markdown.load(st.project.md_path(st.n))
    plan = store.read(st.project.plan_path(st.n))
    lines = [texts.SUMMARY_HEADING]
    for c in plan.get("concepts", []):
        lines += [c.get("name", ""), md.summary(c.get("name", ""))]
    return lines + [texts.LESSONS_HEADING] + [texts.bullet(x) for x in md.lessons]


def status(st):
    """The status of a phase, ending with the next command."""
    n = st.n
    if st.wrong_branch:
        lines = [texts.phase_header(n, st.status),
                 texts.wrong_branch(st.branch, st.wrong_branch, st.project.is_rehearsal),
                 texts.next_line("summarize-phase", n)]
        return "\n".join(lines) + "\n"
    if st.status == "planning":
        lines = [texts.phase_header(n, "planning"), texts.planning_text(n)]
    elif st.status == "done":
        lines = [texts.phase_header(n, "done"), texts.done_text(n)] + _kept(st) + [scorecard.render(st.project, n)]
    elif st.status == "skipped":
        lines = [texts.phase_header(n, "skipped"), texts.skipped_text(n, st.skip_reason)]
    else:
        lines = _table(st, texts.todos_count(st.todos_done, st.todos_total))
        lines += _then(st)
        lines += st.problems
        if st.status == "build" and st.parts_total:
            lines.append(texts.ai_turn(st.part, st.parts_total, st.part_name) if st.turn == "ai"
                         else texts.owner_turn(st.part, st.parts_total))
        elif st.status != "build":
            shown = st.problems + (st.wrap_items if st.status == "tune" else [])
            items = [i for i in st.open_items if i not in shown]
            if items:
                lines += [texts.open_heading()] + [texts.bullet(i) for i in items]
            elif st.status == "wrap-up":
                lines.append(scorecard.render(st.project, n))
    lines.append(next_line(st))
    return "\n".join(lines) + "\n"


def run_number(project):
    """The run of the rehearsal that is going on, 1 if it is not noted."""
    try:
        run = store.read(project.root / ".claude" / "learning" / "local" / "seen.json").get("run")
    except (store.BadJson, OSError):
        return 1
    return run if isinstance(run, int) and not isinstance(run, bool) and run >= 1 else 1


def one_line(project):
    """The status line for SessionStart. `project` is the outer (real) project."""
    return texts.hooks_line(version.VERSION, version.plugin_hash(), project.rehearsal,
                            run_number(project) if project.rehearsal else None, project.problem)
