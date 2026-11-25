"""Read TODO markers and change times from the code folders."""
import os
import re

from .project import is_rehearsal_folder

TODO = re.compile(r"TODO\(owner (\d+)\.(\d+)\)")


def _ids(text):
    seen = []
    for m in TODO.finditer(text):
        i = "%s.%s" % m.groups()
        if i not in seen:
            seen.append(i)
    return seen


def _text(path):
    with open(path, "rb") as f:
        return f.read().decode("utf-8", errors="replace")


def todos(path):
    """TODO ids ("S.T") of a file in order of appearance, each once. A missing file gives []."""
    try:
        return _ids(_text(path))
    except (FileNotFoundError, NotADirectoryError):
        return []


def removed(before, after):
    """TODO ids in `before` that are not in `after`, in order."""
    kept = set(_ids(after))
    return [i for i in _ids(before) if i not in kept]


def _code_files(project):
    """Sorted paths of the files in the code folders with one of the given extensions."""
    exts = tuple(e.lower() for e in project.settings.get("extensions", []))
    found = []
    for d in project.code_dirs:
        for folder, dirs, files in os.walk(d):
            dirs[:] = sorted(x for x in dirs if not is_rehearsal_folder(os.path.join(folder, x)))
            for name in sorted(files):
                if name.lower().endswith(exts) and exts:
                    found.append(os.path.join(folder, name))
    return sorted(found)


def texts(project):
    """(path relative to the root with "/", text) of every code file that can be read."""
    for p in _code_files(project):
        try:
            text = _text(p)
        except OSError:
            continue
        yield os.path.relpath(p, project.root).replace(os.sep, "/"), text


def todos_in_code(project):
    """Every TODO(owner) of the code folders, as ("relative/path", "S.T")."""
    return [(rel, i) for rel, text in texts(project) for i in _ids(text)]


def last_code_change(project):
    """Newest change time of any code file; 0.0 if there is none."""
    times = []
    for p in _code_files(project):
        try:
            times.append(os.stat(p).st_mtime)
        except OSError:
            pass
    return max(times, default=0.0)


def class_and_method(test):
    return tuple(test.split("(", 1)[0].split(".")[-2:])


def has_test(text, test, words=None):
    """True if the code holds the class and the method of a test, each as a whole word.

    words: the set of all words of the text, for a caller that asks for many tests.
    """
    def holds(word):
        if words is not None and word.isidentifier():
            return word in words
        return re.search(r"\b%s\b" % re.escape(word), text) is not None

    return all(holds(w) for w in class_and_method(test))


def tests_in_code(project, tests):
    """Those of the tests whose class and method are in a code file."""
    left, found = list(tests), set()
    for _, text in texts(project) if left else ():
        words = set(re.findall(r"\w+", text))
        found.update(t for t in left if has_test(text, t, words))
        left = [t for t in left if t not in found]
    return [t for t in tests if t in found]


def owner_marks(project, tests):
    """Places of the owner mark in the code files that hold one of the tests, as sorted
    "relative/path:line" strings."""
    mark = project.settings.get("ownerMark", "")
    if not mark:
        return []
    places = []
    for rel, text in texts(project):
        if mark not in text or not any(has_test(text, t) for t in tests):
            continue
        for n, line in enumerate(text.splitlines(), 1):
            if mark in line:
                places.append("%s:%d" % (rel, n))
    return sorted(places)
