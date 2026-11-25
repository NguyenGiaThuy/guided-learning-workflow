"""The check of project.json, the settings of a game."""
import re

from . import texts


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


def _docs_folder(value):
    return _folder(value) and value.split("/")[0].casefold() != ".claude"


def _code_folder(value):
    return value == "." or _folder(value)


def _extension(value):
    return isinstance(value, str) and bool(re.fullmatch(r"(\.[A-Za-z0-9_+#-]+)+", value))


def _text(value):
    return isinstance(value, str) and bool(value.strip())


_CHECKS = {"docs": _docs_folder, "code": _list_of(_code_folder), "extensions": _list_of(_extension),
           "ownerMark": _line, "suites": _list_of(_line), "background": _text}


def problems(settings):
    """Everything that is wrong with the settings, as sentences."""
    found = [texts.setup_key(key, key in settings) for key, good in _CHECKS.items() if not good(settings.get(key))]
    return found + [texts.setup_unknown(key) for key in settings if key not in _CHECKS]
