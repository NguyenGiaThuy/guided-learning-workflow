"""Read phase-N.md: answers, concept summary, lessons and the two process sentences."""
import re

_COMMENT = re.compile(r"<!--.*?-->", re.S)
_HEADING = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.*?)(?:[ \t]+#+)?[ \t]*$")   # a closing # run follows a space
_FENCE = re.compile(r"^ {0,3}(```(?=`*[^`]*$)|~~~)")   # ```x``` on one line is a code span, not a fence
_ITEM = re.compile(r"^(\s*)(?:[-*+]|\d+[.)])(?:\s+(.*))?$")
_PROCESS = re.compile(r"^\s*(?:[-*+]\s+)?[*_]*(surprised me|differently)[*_]*\s*:\s*[*_]*\s*(.*)$", re.I)
_PLACEHOLDER = re.compile(r"^<[^<>]*>$")


def _key(text):
    return " ".join(str(text).split()).casefold()


def _is_text(line):
    """False for an empty line, a heading, and a placeholder such as "- ", "...", "1." or "<answer>"."""
    item = _ITEM.match(line)
    if item:
        line = item.group(2) or ""
    line = line.strip()
    return bool(re.search(r"\w", line)) and not _HEADING.match(line) and not _PLACEHOLDER.match(line)


def _filled(lines):
    """The text of the lines, or "" if they hold nothing but placeholders."""
    return "\n".join(lines).strip() if any(_is_text(x) for x in lines) else ""


def _sections(text):
    """{(section, sub-section or ""): lines}, from the ## and ### headings."""
    found, section, sub, fence = {}, "", "", None
    for line in text.split("\n"):
        mark = _FENCE.match(line)
        if mark and fence is None:
            fence = mark.group(1)
        elif mark and fence == mark.group(1):
            fence = None
        heading = _HEADING.match(line) if fence is None and not mark else None
        level = len(heading.group(1)) if heading else 9
        if level <= 2:
            section, sub = _key(heading.group(2)) if level == 2 else "", ""
            found.setdefault((section, sub), [])   # an empty section is still there
        elif level == 3:
            sub = _key(heading.group(2))
            found.setdefault((section, sub), [])
        else:
            found.setdefault((section, sub), []).append(line)
    return found


def _lessons(lines):
    """The top-level list items; a deeper indented item belongs to the one above it."""
    items = [m for m in (_ITEM.match(x) for x in lines) if m]
    top = min([len(m.group(1)) for m in items], default=0)
    return [m.group(2).strip() for m in items if len(m.group(1)) == top and _is_text(m.group(2) or "")]


def _process(lines):
    """{"surprised me": text, "differently": text}; lines after a key belong to it."""
    found, key = {}, None
    for line in lines:
        m = _PROCESS.match(line)
        if m:
            key, line = m.group(1).lower(), m.group(2)
        if key and _is_text(line):
            found[key] = (found.get(key, "") + " " + line.strip()).strip()
    return found


class PhaseFile:
    def __init__(self, text):
        self._sections = _sections(_COMMENT.sub("", text))
        self.lessons = _lessons(self._sections.get(("lessons", ""), []))
        process = _process(self._sections.get(("process", ""), []))
        self.surprised = process.get("surprised me", "")
        self.differently = process.get("differently", "")

    def has_section(self, name):
        return (_key(name), "") in self._sections

    def answer(self, question):
        return _filled(self._sections.get(("answers", _key(question)), []))

    def summary(self, concept):
        return _filled(self._sections.get(("concept summary", _key(concept)), []))


def load(path):
    """The PhaseFile of a path; a missing file is an empty one. BOM and CRLF are accepted."""
    try:
        with open(path, "rb") as f:
            text = f.read().decode("utf-8-sig", errors="replace")
    except FileNotFoundError:
        text = ""
    return PhaseFile(text.replace("\r\n", "\n").replace("\r", "\n"))
