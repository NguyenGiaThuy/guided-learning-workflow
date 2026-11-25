"""Find the learning project of a working folder and its paths."""
import os
from pathlib import Path

from . import settings as checks
from . import store, texts

LEARNING = Path(".claude") / "learning"
OPEN = "open.json"


class BadSettings(store.BadJson):
    """A project.json that is valid JSON, but cannot be used. Like broken JSON, it must not switch
    the protection off silently."""

    def __init__(self, file, problems):
        super().__init__(file, 1, texts.settings_wrong(file, problems))


def norm(path):
    """The form in which two paths are compared."""
    return os.path.normcase(os.path.realpath(path))


def inside(target, folder):
    """True if target is the folder or lies in it, links resolved."""
    target, folder = norm(target), norm(folder)
    return target == folder or target.startswith(folder.rstrip(os.sep) + os.sep)


def is_rehearsal_folder(folder):
    """True for a folder .claude/learning/rehearsal, by its name."""
    p = Path(folder)
    names = [os.path.normcase(x) for x in (p.parent.parent.name, p.parent.name, p.name)]
    return names == [".claude", "learning", "rehearsal"]


def _read_switch(root):
    """Return (rehearsal, problem) from config.json. Anything unusable means off."""
    path = root / LEARNING / "config.json"
    if not path.exists():
        return False, None
    try:
        data = store.read(path)
    except store.BadJson as e:
        return False, texts.config_problem(path, "line %d" % e.line)
    except OSError as e:
        return False, texts.config_problem(path, e.strerror or "cannot be read")
    if not isinstance(data.get("rehearsal"), bool):
        return False, texts.config_problem(path, '"rehearsal" must be true or false')
    return data["rehearsal"], None


def _read_settings(path):
    data = store.read(path)
    if checks.wrong(data):
        raise BadSettings(path, checks.problems(data))   # an unknown key may be the misspelled one
    return data


class Project:
    def __init__(self, root, settings, rehearsal=False, problem=None):
        self.root = Path(root)
        self.settings = settings
        self.rehearsal = rehearsal
        self.problem = problem

    @property
    def active(self):
        """The project the commands work on: self, or the fake one in rehearsal/."""
        if not self.rehearsal:
            return self
        folder = self.rehearsal_folder
        pj = folder / LEARNING / "project.json"
        return Project(folder, _read_settings(pj) if pj.is_file() else {})

    @property
    def rehearsal_folder(self):
        return self.root / LEARNING / "rehearsal"

    @property
    def is_rehearsal(self):
        """True for the fake project itself. Its branch, merges and test results are simulated."""
        return is_rehearsal_folder(self.root)

    @property
    def docs(self):
        return self.root / self.settings.get("docs", "")

    @property
    def code_dirs(self):
        return [self.root / d for d in self.settings.get("code", [])]

    @property
    def missing_code_dirs(self):
        """The code folders of project.json that do not exist."""
        return [d for d in self.settings.get("code", []) if not (self.root / d).is_dir()]

    def phase_numbers(self):
        nums = []
        if self.docs.is_dir():
            for f in self.docs.iterdir():
                name = f.name
                if name.startswith("phase-") and name.endswith(".json") and not name.endswith(".plan.json"):
                    digits = name[len("phase-"):-len(".json")]
                    if digits.isdigit():
                        nums.append(int(digits))
        return sorted(nums)

    def plan_path(self, n):
        return self.docs / ("phase-%d.plan.json" % n)

    def state_path(self, n):
        return self.docs / ("phase-%d.json" % n)

    def md_path(self, n):
        return self.docs / ("phase-%d.md" % n)

    def note_path(self, n):
        """Where update_state notes the hash of the state file it wrote."""
        return self.root / LEARNING / "local" / "written" / ("phase-%d.json" % n)

    def update_state(self, n, fn):
        """Every write of phase-N.json. The hooks use the note to tell it from any other change."""
        path = self.state_path(n)

        def note():
            try:
                store.write(self.note_path(n), {"hash": store.file_hash(path)})
            except OSError:
                pass   # the record itself is safe; the hooks then ask about the change

        return store.update(path, fn, after=note)

    def update_local(self, name, fn, after=None, tolerant=False):
        """Every read-modify-write of a file in local/, which holds no phase."""
        return store.update(self.root / LEARNING / "local" / name, fn, after=after, tolerant=tolerant)

    def _noted_phases(self):
        """{number: entry} of open.json: {"branch", "locked", "built"} of an open phase and
        {"branch", "done", "locked": []} of a done one, as far as the entries can be used."""
        if self.is_rehearsal:   # its branches are simulated
            return {}
        try:
            data = store.read(self.root / LEARNING / "local" / OPEN)
        except (store.BadJson, OSError):
            return {}
        found = {}
        for key, entry in data.items():
            branch, locked = (entry.get("branch"), entry.get("locked")) if isinstance(entry, dict) else (None, None)
            if not (key.isdigit() and isinstance(branch, str) and isinstance(locked, list)):
                continue
            if entry.get("done"):
                found[int(key)] = {"branch": branch, "done": True, "locked": []}
            else:
                found[int(key)] = {"branch": branch, "locked": [x for x in locked if isinstance(x, str)],
                                   "built": bool(entry.get("built"))}
        return found

    def open_phases(self):
        """{number: {"branch", "locked", "built"}} of the phases that were built on this machine and are
        still open. The phase files are in git, so another branch does not have them; this record is not."""
        return {n: entry for n, entry in self._noted_phases().items() if "done" not in entry}

    def done_phases(self):
        """{number: branch} of the phases that were finished on this machine, merged or not."""
        return {n: entry["branch"] for n, entry in self._noted_phases().items() if "done" in entry}

    def note_open(self, n, data):
        """Keep the record of open and done phases in step with the state of phase n."""
        if self.is_rehearsal:
            return
        entry = None
        if data.get("status") == "build" and data.get("branch"):
            entry = {"branch": data["branch"], "locked": list(data.get("locked") or []), "built": bool(data.get("turn"))}
        elif data.get("status") == "done" and data.get("branch"):
            entry = {"branch": data["branch"], "done": True, "locked": []}
        if self._noted_phases().get(n) == entry:
            return

        def apply(found):
            found.pop(str(n), None)
            if entry:
                found[str(n)] = entry

        try:
            self.update_local(OPEN, apply, tolerant=True)
        except (OSError, store.LockTimeout):
            pass   # the state itself is safe


def find(cwd):
    """Walk up from cwd to a folder with .claude/learning/project.json; None if there is none.

    A rehearsal folder is skipped, so a cwd inside it yields the real parent project.
    Raises store.BadJson if project.json is broken or its settings cannot be used.
    """
    folder = Path(os.path.realpath(cwd))
    for d in [folder] + list(folder.parents):
        pj = d / LEARNING / "project.json"
        if pj.is_file() and not is_rehearsal_folder(d):
            rehearsal, problem = _read_switch(d)
            return Project(d, _read_settings(pj), rehearsal, problem)
    return None
