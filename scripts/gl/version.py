import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
HASHED_DIRS = ("hooks", "scripts", "skills", "templates", "rehearsal")


def _read_version():
    path = ROOT / ".claude-plugin" / "plugin.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)["version"]


VERSION = _read_version()


def plugin_hash(root=None):
    """6 hex characters over the plugin folders; ignores CRLF and __pycache__."""
    base = Path(root) if root is not None else ROOT
    files = []
    for name in HASHED_DIRS:
        folder = base / name
        if not folder.is_dir():
            continue
        for p in folder.rglob("*"):
            if p.is_file() and "__pycache__" not in p.parts:
                files.append((p.relative_to(base).as_posix(), p))
    digest = hashlib.sha256()
    for rel, p in sorted(files):
        data = p.read_bytes().replace(b"\r\n", b"\n")
        digest.update(rel.encode("utf-8") + b"\0")
        digest.update(hashlib.sha256(data).digest())
    return digest.hexdigest()[:6]
