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


_WORD = re.compile(r"[A-Za-z0-9-]+( [A-Za-z0-9-]+)?")


def _word(value):
    return isinstance(value, str) and len(value) <= 20 and bool(_WORD.fullmatch(value))


def _words(value):
    return (isinstance(value, dict) and set(value) <= set(texts.Words._fields)
            and all(_word(v) for v in value.values()))


def _domain(value):
    return _line(value) and len(value) <= 100


# Optional settings: checked only when they are there; a missing one has its default (see Project).
OPTIONAL = {"domain": _domain, "words": _words, "tuning": lambda v: isinstance(v, bool)}


def words_of(settings):
    """The words of these settings: the defaults where they are missing or wrong."""
    given = settings.get("words")
    return texts.DEFAULT_WORDS._replace(**given) if _words(given) else texts.DEFAULT_WORDS


def wrong(settings):
    """Settings that are missing or cannot be used, as sentences."""
    words = words_of(settings)
    return ([texts.setup_key(key, key in settings, words) for key, good in _CHECKS.items()
             if not good(settings.get(key))]
            + [texts.setup_key(key, True, words) for key, good in OPTIONAL.items()
               if key in settings and not good(settings[key])])


def unknown(settings):
    """The keys that are no setting. In the project.json of a game they are only named in the status line."""
    return [key for key in settings if key not in _CHECKS and key not in OPTIONAL]


def problems(settings):
    """Everything that is wrong with the settings, as sentences."""
    return wrong(settings) + [texts.setup_unknown(key) for key in unknown(settings)]
