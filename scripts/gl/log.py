"""The records of a phase: help levels, tweaks, measurements, reasons, ratings, tasks, notes."""
import math
import re

from . import store, texts

TWEAK_ROUNDS = 6
RATINGS = (texts.ON_MY_OWN, texts.WITH_HELP, texts.CANT_YET)
DIRECTIONS = ("up", "down", "none")
FIELDS = {
    "help": ("script", "level"),
    "tweak": ("change", "predicted", "target", "before", "after"),
    "measure": ("target", "value"),
    "reason": ("target", "text"),
    "rating": ("concept", "rating"),
    "task": ("part", "index"),
    "note": ("text",),
}


class LogError(Exception):
    """A record that is not accepted, in words for the user."""


# --- reading single values -------------------------------------------------------------------

def _text(name, value):
    text = str(value).strip()
    if not text:
        raise LogError(texts.log_empty(name))
    return text


def _whole(name, value):
    if isinstance(value, bool) or not re.fullmatch(r"[0-9]{1,9}", str(value).strip()):
        raise LogError(texts.log_not_whole(name, value))
    return int(str(value).strip())


def _number(name, value):
    try:
        if isinstance(value, bool):
            raise ValueError
        number = float(value)
    except (TypeError, ValueError):
        raise LogError(texts.log_not_number(name, value))
    if not math.isfinite(number):
        raise LogError(texts.log_not_number(name, value))
    return int(number) if number.is_integer() else number


def _choice(name, value, allowed):
    if str(value).strip() not in allowed:
        raise LogError(texts.log_choice(name, value, allowed))
    return str(value).strip()


def _known(plan, key, name, value):
    """The id, as it is in the plan, of an entry of plan[key]."""
    ids = [e.get("id") for e in plan.get(key, [])]
    for i in ids:
        if str(i) == str(value).strip():
            return i
    raise LogError(texts.log_unknown(name, value, ids))


# --- the entry of each kind ---------------------------------------------------------------------

def _help(plan, f):
    level = _whole("level", f["level"])
    return {"script": _known(plan, "scripts", "script", f["script"]),
            "level": int(_choice("level", level, ("1", "2", "3", "4")))}


def _tweak(plan, f):
    entry = {"change": _text("change", f["change"]),
             "predicted": _choice("predicted", f["predicted"], DIRECTIONS),
             "target": _known(plan, "targets", "target", f["target"]),
             "before": _number("before", f["before"]), "after": _number("after", f["after"])}
    entry["right"] = entry["predicted"] == direction(entry["before"], entry["after"])
    return entry


def _measure(plan, f):
    return {"target": _known(plan, "targets", "target", f["target"]), "value": _number("value", f["value"])}


def _reason(plan, f):
    return {"target": _known(plan, "targets", "target", f["target"]), "text": _text("text", f["text"])}


def _rating(plan, f):
    return {"concept": _known(plan, "concepts", "concept", f["concept"]),
            "rating": _choice("rating", f["rating"], RATINGS)}


def _note(plan, f):
    return {"text": _text("text", f["text"])}


def _task(plan, f):
    """Part and task are counted from 1 on the command line and stored from 0."""
    part, index = _whole("part", f["part"]), _whole("index", f["index"])
    parts = plan.get("parts", [])
    if not 1 <= part <= len(parts) or not 1 <= index <= len(parts[part - 1].get("tasks", [])):
        raise LogError(texts.log_no_task(part, index))
    return {"part": part - 1, "index": index - 1}


_ENTRIES = {"help": _help, "tweak": _tweak, "measure": _measure, "reason": _reason, "rating": _rating,
            "task": _task, "note": _note}


def direction(before, after):
    return "up" if after > before else "down" if after < before else "none"


# --- adding ---------------------------------------------------------------------------------------

def phase_for(project, n):
    """The phase number to record for: n, or the latest phase."""
    known = project.phase_numbers()
    if n is None and not known:
        raise LogError(texts.NO_PHASE_YET)
    n = max(known) if n is None else n
    if n not in known:
        raise LogError(texts.no_phase(n, known))
    return n


def check_open(n):
    """A check for update_state: refuses a phase that is not in status build."""
    def check(data):
        status = data.get("status") or "planning"
        if status != "build":
            raise LogError(texts.no_record(n, status))
    return check


def _entry(project, n, kind, fields):
    if kind not in FIELDS:
        raise LogError(texts.log_unknown_kind(kind, FIELDS))
    unknown = [f for f in fields if f not in FIELDS[kind]]
    missing = [f for f in FIELDS[kind] if f not in fields]
    if unknown or missing:
        raise LogError(texts.log_fields(kind, FIELDS[kind], missing, unknown))
    return _ENTRIES[kind](store.read(project.plan_path(n)), fields)


def add(project, n, kind, /, **fields):
    """Validate and store one record of phase n (None: the latest); return the reply."""
    project = project.active
    n = phase_for(project, n)
    check = check_open(n)
    check(store.read(project.state_path(n)))   # the status is the first thing to say
    entry = _entry(project, n, kind, fields)

    def apply(data):
        check(data)
        if kind == "task":
            done = data.setdefault("tasksDone", [])
            if entry not in done:
                done.append(entry)
        else:
            data.setdefault("log", []).append(dict({"time": store.now(), "kind": kind}, **entry))

    return _reply(kind, entry, project.update_state(n, apply))


def _reply(kind, entry, data):
    if kind == "task":
        return texts.task_recorded(entry["part"], entry["index"])
    if kind != "tweak":
        return texts.recorded(kind)
    rounds = sum(1 for e in data["log"] if isinstance(e, dict) and e.get("kind") == "tweak")
    reply = texts.tweak_recorded(rounds, TWEAK_ROUNDS, entry["predicted"],
                                 direction(entry["before"], entry["after"]), entry["right"])
    return reply + "\n" + texts.TWEAKS_USED if rounds >= TWEAK_ROUNDS else reply
