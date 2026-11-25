"""/setup-learning: check the settings of a game and write the files of the workflow."""
import os
import re
from pathlib import Path

from . import store, texts, version
from .project import LEARNING

PROJECT = (LEARNING / "project.json").as_posix()
CONFIG = (LEARNING / "config.json").as_posix()
_MARKER = re.compile(r"<!--\s*guided-learning\s*:\s*(?:start|end)\s*-->", re.I)


class SetupError(Exception):
    """Settings or files that cannot be used, in words for the user. Nothing was written."""


# --- checking the settings -------------------------------------------------------------------

def _line(value):
    """True for a text on one line, without spaces around it."""
    return isinstance(value, str) and bool(value) and value == value.strip() and len(value.splitlines()) == 1


def _list_of(good):
    return lambda v: isinstance(v, list) and bool(v) and all(good(x) for x in v) and len(set(v)) == len(v)


def _folder(value):
    """True for a folder below the game's root, written with "/"."""
    if not _line(value) or re.search(r'[\\:*?"<>|]', value) or value.startswith("~"):
        return False
    return not any(part in ("", ".", "..") for part in re.sub("/$", "", value).split("/"))


def _code_folder(value):
    return value == "." or _folder(value)


def _extension(value):
    return isinstance(value, str) and bool(re.fullmatch(r"(\.[A-Za-z0-9_+#-]+)+", value))


def _text(value):
    return isinstance(value, str) and bool(value.strip())


_CHECKS = {"docs": _folder, "code": _list_of(_code_folder), "extensions": _list_of(_extension),
           "ownerMark": _line, "suites": _list_of(_line), "background": _text}


def problems(settings):
    """Everything that is wrong with the settings, as sentences."""
    found = [texts.setup_key(key, key in settings) for key, good in _CHECKS.items() if not good(settings.get(key))]
    return found + [texts.setup_unknown(key) for key in settings if key not in _CHECKS]


def _check(settings, name):
    found = problems(settings)
    if found:
        raise SetupError("\n".join([texts.setup_refused(name)] + [texts.bullet(p) for p in found]))


def _check_docs(root, docs):
    path = root
    for part in docs.rstrip("/").split("/"):
        path = path / part
        if path.exists() and not path.is_dir():
            raise SetupError(texts.setup_not_a_folder(docs))


# --- the text files -----------------------------------------------------------------------------

def _template(name):
    return (version.ROOT / "templates" / name).read_text(encoding="utf-8")


def _load(path):
    """The text of a file with its line endings; "" if there is none."""
    try:
        raw = store.read_bytes(path)
    except FileNotFoundError:
        return ""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as e:
        raise SetupError(texts.bad_encoding(path.name, raw.count(b"\n", 0, e.start) + 1))


def _added(text, addition):
    """The text with the addition at its end, in the line endings of the text."""
    newline = "\r\n" if "\r\n" in text else "\n"
    if text and not text.endswith("\n"):
        text += newline
    return text + addition.replace("\n", newline)


def _ignore(text):
    """(new text or None, message) for .gitignore."""
    there = {line.strip() for line in text.lstrip("\ufeff").split("\n")}
    missing = [line for line in _template("gitignore.txt").split() if line not in there]
    if not missing:
        return None, texts.setup_kept(".gitignore")
    return _added(text, "\n".join(missing) + "\n"), texts.setup_lines_added(".gitignore", missing)


def _section(text):
    """(new text or None, message) for CLAUDE.md."""
    if _MARKER.search(text):
        return None, texts.SETUP_SECTION_THERE
    gap = "\n" if text.strip("\ufeff\r\n") else ""
    return _added(text, gap + _template("claude-md-section.md")), texts.SETUP_SECTION_ADDED


# --- writing -------------------------------------------------------------------------------------

def apply(root, settings, claudeMd=False):
    """Write what is missing in the game at root; return what was done, as sentences.

    An existing project.json stays, and its settings count. All is checked before the first write,
    and project.json is written last, so a game is set up only when the rest is there.
    """
    root = Path(root)
    _check(settings, texts.SETUP_GIVEN)
    existing = (root / PROJECT).is_file()
    if existing:
        settings = store.read(root / PROJECT)
        _check(settings, PROJECT)
    _check_docs(root, settings["docs"])
    writes, done = [], []

    def create(rel, write, content):
        if os.path.lexists(root / rel):
            done.append(texts.setup_kept(rel))
        else:
            writes.append((write, root / rel, content))
            done.append(texts.setup_written(rel))

    def extend(name, change):
        path = Path(os.path.realpath(root / name))   # a linked file stays a link
        text, message = change(_load(path))
        if text is not None:
            writes.append((store.write_text, path, text))
        done.append(message)

    create(settings["docs"].rstrip("/") + "/README.md", store.write_text, _template("README.md"))
    extend(".gitignore", _ignore)
    if claudeMd:
        extend("CLAUDE.md", _section)
    create(CONFIG, store.write, {"rehearsal": False})
    create(PROJECT, store.write, settings)
    for write, path, content in writes:
        write(path, content)
    if existing:
        done.append(texts.SETUP_SETTINGS_BY_HAND)
    return done + [texts.setup_no_folder(d) for d in settings["code"] if not (root / d).is_dir()]
