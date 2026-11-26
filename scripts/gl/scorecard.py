"""The scorecard of a phase, worked out from the saved data. It shows a trend and gives no grade."""
from . import markdown, results, state, store, texts


def _passing(project, data, plan, fresh):
    """(owner scripts whose planned tests all passed, highest help level of each script by label)."""
    helped = state.help_levels(state.log_of(data))
    passing, levels = 0, {}
    for s in plan.get("scripts", []):
        tests = [str(t) for t in s.get("tests", [])]
        outcomes = [state.outcome(project, data, t, fresh) for t in tests]
        passing += 1 if all(o == "passed" for o in outcomes) else 0
        levels[texts.script_label(s.get("id"), s.get("name", ""))] = helped.get(str(s.get("id")), 0)
    return passing, levels


def compute(project, n):
    """The five rows of phase n as a dict. A done phase uses its stored results as they are: later
    phases change the code, and that must not turn an earlier scorecard into a worse one."""
    data, plan = store.read(project.state_path(n)), store.read(project.plan_path(n))
    done = data.get("status") == "done"
    fresh = {s: done or results.fresh(project, data, s) for s in project.settings.get("suites", [])}
    log = state.log_of(data)
    passing, levels = _passing(project, data, plan, fresh)
    tweaks = [e for e in log if e.get("kind") == "tweak"]
    rated = state.ratings(data)
    md = markdown.load(project.md_path(n))
    return {
        "build": {"passing": passing, "total": len(plan.get("scripts", [])), "help": levels},
        "predict": {"right": sum(1 for e in tweaks if e.get("right") is True), "total": len(tweaks)},
        "balance": {"met": state.targets_met(plan, log)[0], "total": len(plan.get("targets", []))},
        "explain": {c.get("name", ""): rated.get(str(c.get("id")), texts.NOT_RATED)
                    for c in plan.get("concepts", [])},
        "process": {"surprised": md.surprised, "differently": md.differently},
    }


def _previous(project, n):
    """The scorecard of the phase before n, or None if that phase is not done."""
    if n > 1 and store.read(project.state_path(n - 1)).get("status") == "done":
        return compute(project, n - 1)
    return None


def render(project, n):
    """The scorecard as plain text, a heading and one row per line."""
    card, before = compute(project, n), _previous(project, n)

    def trend(line, key, a, b):
        if key in ("predict", "balance") and before and not (before["balance"]["total"] or before["predict"]["total"]):
            return line   # the phase before had no tuning: nothing to compare with
        return line if before is None else "%s %s" % (line, texts.last_phase("%d/%d" % (before[key][a], before[key][b])))

    b, p, bal = card["build"], card["predict"], card["balance"]
    tuned = bal["total"] or p["total"]   # a phase without targets and without tweaks had no tuning
    return "\n".join([
        texts.scorecard_heading(n),
        trend(texts.score_build(b["passing"], b["total"], b["help"]), "build", "passing", "total"),
    ] + ([
        trend(texts.score_predict(p["right"], p["total"]), "predict", "right", "total"),
        trend(texts.score_balance(bal["met"], bal["total"], project.words), "balance", "met", "total"),
    ] if tuned else []) + [
        texts.score_explain(card["explain"]),
        texts.score_process(card["process"]["surprised"], card["process"]["differently"]),
    ])


def write_once(project, n):
    """Append the scorecard to phase-N.md as "## Scorecard" unless it is there. Nothing else is changed."""
    path = project.md_path(n)
    try:
        raw = path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return
    if markdown.load(path).has_section("scorecard"):
        return
    eol = "\r\n" if "\r\n" in raw else "\n"
    body = render(project, n).split("\n")[1:]
    gap = "" if not raw or raw.endswith(("\n\n", "\r\n\r\n")) else (eol if raw.endswith("\n") else eol * 2)
    section = eol.join([texts.SCORECARD_SECTION, ""] + body) + eol
    store.write_text(path, raw + gap + section)
