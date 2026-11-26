"""The check of a plan file: everything that keeps it from being approved."""
import math
import re

from . import store, texts
from .project import inside


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


def part_scripts(part):
    ids = part.get("scripts")
    return [str(i) for i in ids] if isinstance(ids, list) else []


def _in_code(project, path):
    """True for a path below the game's root that the scan of the code folders finds."""
    if re.match(r"[A-Za-z]:|[/\\]", path) or ".." in re.split(r"[/\\]", path):
        return False
    extensions = tuple(e.lower() for e in project.settings.get("extensions", []))
    return path.lower().endswith(extensions) and any(inside(project.root / path, d) for d in project.code_dirs)


def _script_gaps(project, scripts, concepts, parts):
    gaps = []
    if not 1 <= len(scripts) <= 5:
        gaps.append(texts.gap_script_count(len(scripts)))
    known = {str(c.get("id")) for c in concepts}
    placed = [i for p in parts for i in part_scripts(p)]
    for s in scripts:
        sid = str(s.get("id"))
        label = texts.script_label(sid, s.get("name", ""))
        if not re.fullmatch("[0-9]+", sid) and s.get("id") not in (None, ""):
            gaps.append(texts.gap_script_id(sid))
        for key in ("path", "concept"):
            if not _filled(s.get(key)):
                gaps.append(texts.gap_script(label, key))
        if _filled(s.get("path")) and not _in_code(project, s["path"]):
            gaps.append(texts.gap_script_path(label, s["path"], project.settings.get("code", []),
                                              project.settings.get("extensions", [])))
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
        gaps += [texts.gap_part_script(label, sid) for sid in part_scripts(p) if sid not in known]
    return gaps


def _target_gaps(targets, words, tuning):
    gaps = [] if targets or not tuning else [texts.gap_no_target(words)]
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


def plan_gaps(project, n, tuning=None):
    """Everything that keeps the plan of phase n from being approved.

    tuning: whether a target is needed; None means the setting of the project (a changed plan passes the value
    stored at its approval, so switching the setting later does not change what an approved plan needs).
    """
    plan, gaps = store.read(project.plan_path(n)), []
    concepts, parts, scripts, targets, questions = [
        _entries(plan, k, gaps) for k in ("concepts", "parts", "scripts", "targets", "questions")]
    if not concepts:
        gaps.append(texts.GAP_NO_CONCEPT)
    gaps += [texts.gap_concept_name(c.get("id")) for c in concepts if not _filled(c.get("name"))]
    gaps += _script_gaps(project, scripts, concepts, parts) + _part_gaps(parts, scripts) + _target_gaps(targets, project.words, project.tuning if tuning is None else tuning)
    asked = {str(q.get("concept")) for q in questions}
    gaps += [texts.gap_question(c.get("name") or c.get("id")) for c in concepts if str(c.get("id")) not in asked]
    gaps += [texts.gap_points(q.get("id")) for q in questions if not _filled_list(q.get("points"))]
    return gaps
