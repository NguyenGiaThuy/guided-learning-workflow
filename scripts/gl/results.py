"""Read test result files (NUnit 3, JUnit, plain lines) and keep them in the phase state."""
import os
import xml.etree.ElementTree as ET

from . import scan, store, texts

_BOM = b"\xef\xbb\xbf"
_ROOTS = ("test-run", "test-results", "testsuites", "testsuite")
_NUNIT = {"passed": "passed", "success": "passed",
          "failed": "failed", "failure": "failed", "error": "failed"}
_PLAIN = {"pass": "passed", "passed": "passed", "fail": "failed", "failed": "failed"}


class ResultError(Exception):
    """A problem with a result file or suite, in words for the user."""


def _merge(found, name, outcome):
    if found.get(name) != "failed":   # a failure of a repeated name is never hidden
        found[name] = outcome


def _parse_xml(path, raw):
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        raise ResultError(texts.result_xml_broken(path, str(e)))
    if root.tag not in _ROOTS:
        raise ResultError(texts.result_unknown_format(path))
    found = {}
    for case in root.iter("test-case"):
        name = case.get("fullname") or case.get("name") or ""
        outcome = _NUNIT.get((case.get("result") or "").lower(), "skipped")
        _merge(found, name, outcome)
    for case in root.iter("testcase"):
        name = case.get("name") or ""
        if case.get("classname"):
            name = case.get("classname") + "." + name
        kids = {k.tag for k in case}
        outcome = "failed" if kids & {"failure", "error"} else "skipped" if "skipped" in kids else "passed"
        _merge(found, name, outcome)
    return found


def _parse_plain(path, raw):
    found = {}
    for n, line in enumerate(raw.decode("utf-8", errors="replace").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        name, _, word = line.rpartition(",")
        outcome = _PLAIN.get(word.strip().lower())
        if not name.strip() or outcome is None:
            raise ResultError(texts.result_bad_line(path, n))
        _merge(found, name.strip(), outcome)
    return found


def parse(path):
    """Return {test name: "passed" | "failed" | "skipped"}. The format is found by content."""
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError as e:
        raise ResultError(texts.result_unreadable(path, e.strerror or str(e)))
    if raw.startswith(_BOM):
        raw = raw[len(_BOM):]
    if raw.lstrip().startswith(b"<"):
        return _parse_xml(path, raw)
    return _parse_plain(path, raw)


def matches(planned, actual):
    """True if a recorded test name is a planned one: equal, or equal once a "(...)" part
    is cut off, or ending with "." + planned (a namespace in front)."""
    cut = actual.split("(", 1)[0]
    return any(a == planned or a.endswith("." + planned) for a in (actual, cut))


def without_case(name):
    """The name of a test without the "(...)" of its case."""
    return name.split("(", 1)[0]


def known(entry):
    """Every test name, without cases, that the results of a suite have had in this phase; sorted."""
    entry = entry if isinstance(entry, dict) else {}
    kept, tests = entry.get("known"), entry.get("tests")
    names = {k for k in kept if isinstance(k, str)} if isinstance(kept, list) else set()
    names |= {without_case(k) for k in tests} if isinstance(tests, dict) else set()
    return sorted(names - {""})


def record(project, n, suite, path, check=None):
    """Store the passed and failed tests of a result file under results[suite] of phase n.

    Returns them. check(state) is called inside the update and may raise to refuse it.
    """
    suites = project.settings.get("suites", [])
    if suite not in suites:
        raise ResultError(texts.result_unknown_suite(suite, suites))
    found = parse(path)
    if not found:
        raise ResultError(texts.result_empty(path))
    tests = {k: v for k, v in found.items() if v != "skipped"}
    if not tests:
        raise ResultError(texts.result_nothing_run(path))
    time = os.stat(path).st_mtime
    limit = scan.last_code_change(project)

    def apply(state):
        if check:
            check(state)
        stored = state.setdefault("results", {})
        old = stored.get(suite)
        if isinstance(old, dict) and isinstance(old.get("tests"), dict) and old.get("time", -1) >= limit:
            # Fresh results are added to. min() keeps the oldest part honest: if the new
            # file predates the last code change, the merged suite stops being fresh.
            stored[suite] = {"time": min(old["time"], time), "tests": dict(old["tests"], **tests)}
        else:
            stored[suite] = {"time": time, "tests": tests}
        stored[suite]["known"] = sorted(set(known(old)) | set(known(stored[suite])))

    project.update_state(n, apply)
    return tests


def fresh(project, state, suite):
    """True if the suite has results at least as new as the last code change.

    Equality counts as fresh: file times tick coarsely, and a run saved in the same
    instant as the code cannot be told apart from one that came after it.
    """
    entry = (state.get("results") or {}).get(suite)
    if not isinstance(entry, dict) or not isinstance(entry.get("time"), (int, float)):
        return False
    return entry["time"] >= scan.last_code_change(project)
