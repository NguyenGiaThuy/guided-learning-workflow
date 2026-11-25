"""Shared test helpers. Add keyword arguments to make_project as later tests need them."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

PROJECT_JSON = {
    "docs": "Docs/learning",
    "code": ["src"],
    "extensions": [".cs"],
    "ownerMark": "[Explicit(\"Owner\")]",
    "suites": ["Unit"],
    "background": "C# web developer",
}


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(data, indent=2) + "\n").encode("utf-8"))


def make_project(tmp, phases=None, settings=None, files=None):
    """Build a Lantern Keeper project under tmp and return its root.

    phases: {n: {"state": dict, "plan": dict, "md": str}}; each key is optional.
    settings: keys that replace those of PROJECT_JSON.
    files: {relative path: text} of code files to write under the root.
    """
    root = Path(tmp)
    cfg = dict(PROJECT_JSON, **(settings or {}))
    write_json(root / ".claude" / "learning" / "project.json", cfg)
    docs = root / cfg["docs"]
    docs.mkdir(parents=True, exist_ok=True)
    for d in cfg["code"]:
        (root / d).mkdir(parents=True, exist_ok=True)
    for n, parts in (phases or {}).items():
        if "state" in parts:
            write_json(docs / ("phase-%d.json" % n), parts["state"])
        if "plan" in parts:
            write_json(docs / ("phase-%d.plan.json" % n), parts["plan"])
        if "md" in parts:
            (docs / ("phase-%d.md" % n)).write_bytes(parts["md"].encode("utf-8"))
    for rel, text in (files or {}).items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
    return root


def shell(todos):
    """Text of a code file that still holds the given TODO ids ("1.3", ...)."""
    lines = ["class Shell {"]
    for t in todos:
        lines.append("    // TODO(owner %s) do something" % t)
    lines.append("}")
    return chr(10).join(lines) + chr(10)


def script(sid, name, todos, tests=(), path=None):
    return {"id": sid, "name": name, "path": path or "src/%s.cs" % name, "concept": "ai",
            "todos": list(todos), "tests": list(tests)}


def plan(scripts, parts=None, targets=None):
    """A Lantern Keeper plan; by default all scripts are in one part."""
    return {"phase": 2, "concepts": [{"id": "ai", "name": "Enemy AI"}],
            "parts": parts or [{"name": "Part 1", "tasks": ["Shells and tests"],
                                "scripts": [s["id"] for s in scripts]}],
            "scripts": scripts, "targets": targets or [], "questions": []}


FULL_MD = """# Phase 2

## Notes for later

## Answers

### q1
It takes the nearest lamp in range.

## Concept summary

### Enemy AI
A state machine with two states.

## Lessons
- one
- two
- three

## Process
Surprised me: the tests came first
Differently: start smaller
"""

FRESH = 4000000000.0   # a result time after any file written by a test
OLD = 1.0


def suite_result(tests, time=FRESH):
    return {"time": time, "tests": tests}


def set_switch(root, text):
    """Write config.json with the given raw text (str or bytes)."""
    p = Path(root) / ".claude" / "learning" / "config.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(text if isinstance(text, bytes) else text.encode("utf-8"))


def full_plan(n=2, parts=None):
    """A complete plan: three scripts (Moth, Lamp, Keeper) in one part, one concept, one target."""
    scripts = [script(1, "Moth", ["1.1", "1.2"], ["MothTests.Turns", "MothTests.Dies"]),
               script(2, "Lamp", ["2.1"], ["LampTests.Glows"]),
               script(3, "Keeper", ["3.1"], ["KeeperTests.Walks"])]
    targets = [{"id": "wins", "text": "Average player wins", "measure": "20 bot runs",
                "settings": ["Moth.speed"], "min": 40, "max": 60}]
    result = plan(scripts, parts, targets)
    result.update(phase=n, questions=[{"id": "q1", "concept": "ai", "text": "How does it choose a target?",
                                       "points": ["nearest", "in range"]}])
    return result


TWO_PARTS = [{"name": "Moths", "tasks": ["Shells", "Tests"], "scripts": [1, 2]},
             {"name": "Keeper", "tasks": ["Shell"], "scripts": [3]}]

# The test code of full_plan, without the owner mark.
TEST_CODE = {"src/MothTests.cs": "class MothTests { void Turns() {} void Dies() {} }\n",
             "src/LampTests.cs": "class LampTests { void Glows() {} }\n",
             "src/KeeperTests.cs": "class KeeperTests { void Walks() {} }\n"}
