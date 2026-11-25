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
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n")


def make_project(tmp, phases=None, settings=None):
    """Build a Lantern Keeper project under tmp and return its root.

    phases: {n: {"state": dict, "plan": dict, "md": str}}; each key is optional.
    settings: keys that replace those of PROJECT_JSON.
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
            (docs / ("phase-%d.md" % n)).write_text(parts["md"], encoding="utf-8", newline="\n")
    return root


def set_switch(root, text):
    """Write config.json with the given raw text (str or bytes)."""
    p = Path(root) / ".claude" / "learning" / "config.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(text if isinstance(text, bytes) else text.encode("utf-8"))
