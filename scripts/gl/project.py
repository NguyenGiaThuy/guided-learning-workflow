"""Find the learning project of a working folder and its paths."""
import os
from pathlib import Path

from . import store, texts

LEARNING = Path(".claude") / "learning"


def _is_rehearsal_folder(folder):
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
        folder = self.root / LEARNING / "rehearsal"
        pj = folder / LEARNING / "project.json"
        return Project(folder, store.read(pj))

    @property
    def docs(self):
        return self.root / self.settings.get("docs", "")

    @property
    def code_dirs(self):
        return [self.root / d for d in self.settings.get("code", [])]

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


def find(cwd):
    """Walk up from cwd to a folder with .claude/learning/project.json; None if there is none.

    A rehearsal folder is skipped, so a cwd inside it yields the real parent project.
    Raises store.BadJson if project.json is broken.
    """
    folder = Path(os.path.realpath(cwd))
    for d in [folder] + list(folder.parents):
        pj = d / LEARNING / "project.json"
        if pj.is_file() and not _is_rehearsal_folder(d):
            rehearsal, problem = _read_switch(d)
            return Project(d, store.read(pj), rehearsal, problem)
    return None
