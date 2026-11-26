"""/setup-learning: check the settings of a game and write the files of the workflow."""
import os
import re
from pathlib import Path

from . import state, store, texts, version
from .project import LEARNING, Project
from .settings import problems, unknown, wrong

PROJECT = (LEARNING / "project.json").as_posix()
CONFIG = (LEARNING / "config.json").as_posix()
_MARKER = re.compile(r"<!--\s*guided-learning\s*:\s*(?:start|end)\s*-->", re.I)


class SetupError(Exception):
    """Settings or files that cannot be used, in words for the user. Nothing was written."""


# --- checking the settings -------------------------------------------------------------------

def _check(found, name):
    """Refuse settings with these problems."""
    if found:
        raise SetupError("\n".join([texts.setup_refused(name)] + [texts.bullet(p) for p in found]))


def _check_folder(root, folder):
    path = root
    for part in folder.rstrip("/").split("/"):
        path = path / part
        if path.exists() and not path.is_dir():
            raise SetupError(texts.setup_not_a_folder(folder))


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

def apply(root, settings, claudeMd=False, own=False):
    """Write what is missing in the game at root; return what was done, as sentences.

    An existing project.json stays, and its settings count. own: the settings are that file, in which
    an unknown key is only named. All is checked before the first write,
    and project.json is written last, so a game is set up only when the rest is there.
    """
    root = Path(root)
    _check(wrong(settings) if own else problems(settings), texts.SETUP_GIVEN)
    existing = (root / PROJECT).is_file()
    if existing:
        settings = store.read(root / PROJECT)
        _check(wrong(settings), PROJECT)
    _check_folder(root, LEARNING.as_posix())
    _check_folder(root, settings["docs"])
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
        done.append(texts.setup_settings_by_hand(Project(root, settings).words))
        done += [texts.unknown_settings(unknown(settings))] if unknown(settings) else []
    here = Project(root, settings)
    done += [texts.setup_no_folder(d) for d in here.missing_code_dirs]
    return done + ([texts.setup_ignored(here.words)] if state.is_ignored(here, PROJECT) else [])
