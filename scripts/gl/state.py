"""Work out where a phase stands from the project files. Nothing here writes a file."""
import os
import subprocess

from . import markdown, results, scan, store, texts

DETACHED = texts.DETACHED
BRANCH_STATUSES = ("build", "tune", "wrap-up")
GIT_TIMEOUT = 15


class ScriptState:
    def __init__(self, sid, name, path, handed):
        self.id = sid
        self.name = name
        self.path = path
        self.handed = handed          # its part was handed over to the owner
        self.status = "not started"   # done | in progress | not started | unknown
        self.why = None               # for unknown: "old" or "not run"
        self.todos_done = 0
        self.todos_total = 0
        self.todos_left = []          # ids still in the file, in file order
        self.tests_passed = 0
        self.tests_total = 0
        self.failing = []             # planned tests with a failed result
        self.unrun = []               # planned tests without any result
        self.help = 0
        self.file_missing = False
        self.lost = []                # planned TODOs missing from the file before the hand-over

    @property
    def label(self):
        return texts.script_label(self.id, self.name)

    def problems(self):
        items = [texts.lost_todo(t, self.label, self.path) for t in self.lost]
        if self.file_missing:
            items.append(texts.script_file_missing(self.label, self.path))
        return items

    def open_items(self):
        items = self.problems()
        if self.todos_left:
            items.append(texts.todos_left(self.label, len(self.todos_left)))
        if not self.handed:
            return items
        if self.failing:
            items.append(texts.tests_failing(self.label, self.failing))
        if self.status == "unknown":
            items.append(texts.tests_old(self.label) if self.why == "old"
                         else texts.tests_not_run(self.label, self.unrun))
        return items


class PhaseState:
    def __init__(self, n):
        self.n = n
        self.status = "planning"
        self.turn = None
        self.part = 0
        self.parts_total = 0
        self.part_name = ""
        self.branch = None
        self.skip_reason = None
        self.scripts = []
        self.todos_done = 0
        self.todos_total = 0
        self.next_todo = None
        self.next_script = None       # id of the script that holds next_todo
        self.targets_met = 0
        self.targets_total = 0
        self.targets_open = []        # ids with neither a value in range nor a reason
        self.open_items = []          # everything /finish-phase checks and misses
        self.wrap_items = []          # the part of open_items that belongs to the wrap-up
        self.plan_changed = False     # the plan differs from the approved one
        self.problems = []            # lost TODOs and missing files: shown even while building
        self.wrong_branch = None
        self.lost_todos = []          # "S.T" of planned TODOs that were never in their file


# --- git (the one seam for the branch) ------------------------------------------------------

def _git(project, *args):
    """Run git quietly in the project folder; return (returncode, stdout), or None if it cannot run.

    Only plumbing commands are used, and the answers are read from return codes and refs,
    never from messages, so the user's language does not matter.
    """
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = 0x08000000   # CREATE_NO_WINDOW
    env = dict(os.environ, LC_ALL="C", GIT_TERMINAL_PROMPT="0")
    try:
        done = subprocess.run(["git", "-C", str(project.root)] + list(args), stdin=subprocess.DEVNULL,
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=GIT_TIMEOUT,
                              env=env, **kwargs)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.returncode, done.stdout.decode("utf-8", errors="replace").strip()


def current_branch(project):
    """The checked-out branch; DETACHED on a detached HEAD; None without git or repository."""
    found = _git(project, "symbolic-ref", "-q", "HEAD")
    if found is None:
        return None
    code, out = found
    if code == 0 and out.startswith("refs/heads/"):
        return out[len("refs/heads/"):]
    if code == 1:   # HEAD exists but is not a symbolic ref
        return DETACHED
    return None


def _ref_exists(project, ref):
    found = _git(project, "rev-parse", "--verify", "-q", ref)
    return found is not None and found[0] == 0


def _is_ancestor(project, ref, other):
    found = _git(project, "merge-base", "--is-ancestor", ref, other)
    return found is None or found[0] != 1


def _main_branch(project):
    """(name, its existing refs) of the main branch: the target of origin/HEAD, else a local
    main, else master. (None, []) if there is none."""
    remote = "refs/remotes/origin/"
    names = []
    found = _git(project, "symbolic-ref", "-q", remote + "HEAD")
    if found is not None and found[0] == 0 and found[1].startswith(remote):
        name = found[1][len(remote):]
        names.append((name, ["refs/heads/" + name, remote + name]))
    names += [(name, ["refs/heads/" + name]) for name in ("main", "master")]
    for name, refs in names:
        refs = [r for r in refs if _ref_exists(project, r)]
        if refs:
            return name, refs
    return None, []


def is_merged(project, branch):
    """True if the work of branch is merged; also without git, repository or that branch.

    While another branch is checked out: branch is an ancestor of HEAD. While branch itself is
    checked out that is always so; then it is the main branch, or is contained in it, or there
    is no main branch to merge into.
    """
    ref = "refs/heads/" + branch
    if not _ref_exists(project, ref):
        return True
    if current_branch(project) != branch:
        return _is_ancestor(project, ref, "HEAD")
    name, refs = _main_branch(project)
    return name is None or name == branch or any(_is_ancestor(project, ref, r) for r in refs)


# --- pieces of the computation ----------------------------------------------------------------

def _outcome(project, data, planned, fresh):
    """"passed", "failed", "stale" (a result older than the code) or "none" for a planned test."""
    held = []
    for suite in project.settings.get("suites", []):
        entry = (data.get("results") or {}).get(suite)
        tests = entry.get("tests") if isinstance(entry, dict) else None
        if not isinstance(tests, dict):
            continue
        hits = [o for name, o in tests.items() if results.matches(planned, name)]
        if hits:
            held.append((hits, fresh[suite]))
    if not held:
        return "none"
    if not all(f for _, f in held):
        return "stale"
    return "passed" if all(o == "passed" for hits, _ in held for o in hits) else "failed"


def _help_levels(log):
    levels = {}
    for e in log:
        if isinstance(e, dict) and e.get("kind") == "help" and isinstance(e.get("level"), int):
            key = str(e.get("script"))
            levels[key] = max(levels.get(key, 0), e["level"])
    return levels


def _script(project, data, plan_script, handed, fresh, helped):
    sc = ScriptState(plan_script.get("id"), plan_script.get("name", ""), plan_script.get("path", ""), handed)
    planned = [str(t) for t in plan_script.get("todos", [])]
    tests = [str(t) for t in plan_script.get("tests", [])]
    sc.todos_total, sc.tests_total = len(planned), len(tests)
    sc.help = helped.get(str(sc.id), 0)
    file = project.root / sc.path
    if not file.is_file():
        sc.file_missing = handed   # before the hand-over the file need not exist yet
        return sc
    inside = scan.todos(file)
    missing = [t for t in planned if t not in inside]
    sc.todos_left = list(inside)   # a TODO that is not in the plan still counts
    if not handed:
        sc.lost = missing
        return sc
    sc.todos_done = len(missing)
    outcomes = {t: _outcome(project, data, t, fresh) for t in tests}
    sc.tests_passed = sum(1 for o in outcomes.values() if o == "passed")
    sc.failing = [t for t, o in outcomes.items() if o == "failed"]
    sc.unrun = [t for t, o in outcomes.items() if o == "none"]
    if sc.todos_left:
        sc.status = "in progress" if sc.todos_done else "not started"
    elif sc.failing:
        sc.status = "in progress"
    elif sc.tests_passed == sc.tests_total:
        sc.status = "done"
    else:
        sc.status = "unknown"
        sc.why = "old" if "stale" in outcomes.values() else "not run"
    return sc


def _targets(plan, log):
    """(count of met targets, ids that are neither met nor have a written reason)."""
    met, open_ = 0, []
    for t in plan.get("targets", []):
        tid = t.get("id")
        values = [e.get("value") for e in log
                  if isinstance(e, dict) and e.get("kind") == "measure" and e.get("target") == tid]
        value = values[-1] if values else None
        ok = isinstance(value, (int, float)) and not isinstance(value, bool)
        ok = ok and (t.get("min") is None or value >= t["min"]) and (t.get("max") is None or value <= t["max"])
        reasoned = any(isinstance(e, dict) and e.get("kind") == "reason" and e.get("target") == tid for e in log)
        met += 1 if ok else 0
        if not ok and not reasoned:
            open_.append(tid)
    return met, open_


def suite_items(project, data, leave_out=()):
    """What is wrong with the recorded suites, without the failures of the tests in leave_out."""
    items = []
    for suite in project.settings.get("suites", []):
        entry = (data.get("results") or {}).get(suite)
        if not isinstance(entry, dict) or not isinstance(entry.get("tests"), dict):
            items.append(texts.suite_not_recorded(suite))
        elif not results.fresh(project, data, suite):
            items.append(texts.suite_old(suite))
        else:
            failed = sorted(k for k, v in entry["tests"].items() if v == "failed"
                            and not any(results.matches(t, k) for t in leave_out))
            if failed:
                items.append(texts.suite_failing(suite, failed))
    return items


def _log(data):
    return [e for e in data.get("log", []) if isinstance(e, dict)] if isinstance(data.get("log"), list) else []


def _ratings(data):
    """{concept id: its last rating}"""
    return {str(e.get("concept")): e.get("rating") for e in _log(data) if e.get("kind") == "rating"}


def _wrap_items(project, n, plan, data):
    """What the wrap-up still needs: answers, ratings, concept summary, lessons, process."""
    md = markdown.load(project.md_path(n))
    rated = _ratings(data)
    concepts = [(str(c.get("id")), c.get("name", "")) for c in plan.get("concepts", [])]
    asked = [(str(q.get("concept")), q.get("id")) for q in plan.get("questions", [])]
    items = [texts.answer_missing(name) for cid, name in concepts
             if not any(md.answer(q) for c, q in asked if c == cid)]
    items += [texts.rating_missing(name) for cid, name in concepts
              if rated.get(cid) not in (texts.ON_MY_OWN, texts.WITH_HELP)]
    items += [texts.summary_missing(name) for _, name in concepts if not md.summary(name)]
    if not 3 <= len(md.lessons) <= 5:
        items.append(texts.lessons_count(len(md.lessons)))
    if not md.surprised:
        items.append(texts.SURPRISED_MISSING)
    if not md.differently:
        items.append(texts.DIFFERENTLY_MISSING)
    return items


def carry_over(project, n):
    """(names of the weak concepts, the "Differently" text) of phase n, for the phase after it."""
    plan, data = store.read(project.plan_path(n)), store.read(project.state_path(n))
    rated = _ratings(data)
    weak = [c.get("name", "") for c in plan.get("concepts", []) if rated.get(str(c.get("id"))) == texts.WITH_HELP]
    return weak, markdown.load(project.md_path(n)).differently


def _stray_todos(project, plan_scripts):
    """TODOs of this phase's scripts in files that are no owner script of the phase."""
    ids = {str(s.get("id")) for s in plan_scripts}
    own = {_norm(project.root / s.get("path", "")) for s in plan_scripts}
    return [texts.todo_elsewhere(todo, rel) for rel, todo in scan.todos_in_code(project)
            if todo.split(".")[0] in ids and _norm(project.root / rel) not in own]


def _norm(path):
    return os.path.normcase(os.path.realpath(path))


def plan_differs(project, n, data):
    """True if the plan file is not the approved one (it may be gone)."""
    approved = data.get("planHash")
    if not approved:
        return False
    try:
        return store.file_hash(project.plan_path(n)) != approved
    except FileNotFoundError:
        return True


# --- the computation -----------------------------------------------------------------------

def compute(project, n):
    """Return the PhaseState of phase n, worked out from the files. Nothing is written."""
    data = store.read(project.state_path(n))
    plan = store.read(project.plan_path(n))
    st = PhaseState(n)
    st.status = data.get("status") or "planning"
    st.branch = data.get("branch") or None
    if isinstance(data.get("skip"), str):
        st.skip_reason = data["skip"]
    if st.status == "planning":
        st.open_items.append(texts.plan_not_approved(n))
    if st.status == "build":
        _build(project, st, data, plan)
    if st.status in BRANCH_STATUSES and st.branch:
        current = current_branch(project)
        if current is not None and current != st.branch:
            st.wrong_branch = current
    return st


def _build(project, st, data, plan):
    log = _log(data)
    plan_scripts = plan.get("scripts", [])
    parts = plan.get("parts") or [{"name": "", "scripts": [s.get("id") for s in plan_scripts]}]
    part = data.get("part") if isinstance(data.get("part"), int) else 0
    stored_turn = "owner" if data.get("turn") == "owner" else "ai"
    # A part is handed over if it is before the current one, or is the current one and the owner's turn.
    handed_parts = [i for i in range(len(parts)) if i < part or (i == part and stored_turn == "owner")]
    handed_ids = {str(i) for p in handed_parts for i in parts[p].get("scripts", [])}

    fresh = {s: results.fresh(project, data, s) for s in project.settings.get("suites", [])}
    helped = _help_levels(log)
    if len(handed_parts) == len(parts):   # a script in no part is reachable once all parts are handed over
        listed = {str(i) for p in parts for i in p.get("scripts", [])}
        handed_ids |= {str(s.get("id")) for s in plan_scripts if str(s.get("id")) not in listed}
    st.scripts = [_script(project, data, s, str(s.get("id")) in handed_ids, fresh, helped) for s in plan_scripts]
    st.parts_total = len(parts)
    st.todos_total = sum(s.todos_total for s in st.scripts)
    st.todos_done = sum(s.todos_done for s in st.scripts)
    st.lost_todos = [t for s in st.scripts for t in s.lost]

    handed_done = all(s.status == "done" for s in st.scripts if s.handed)
    st.turn, st.part = stored_turn, part
    if stored_turn == "owner" and handed_done and part + 1 < len(parts):
        st.turn, st.part = "ai", part + 1
    st.part_name = parts[st.part].get("name", "") if st.part < len(parts) else ""

    for s in st.scripts:
        if s.handed and s.status != "done":
            st.next_script = s.id
            st.next_todo = s.todos_left[0] if s.todos_left else None
            break
    st.targets_total = len(plan.get("targets", []))
    st.targets_met, st.targets_open = _targets(plan, log)

    if not plan_scripts and not plan.get("parts"):
        item = texts.plan_missing(project.plan_path(st.n).name)
        st.parts_total = 0
        st.problems.append(item)
        st.open_items.append(item)
        return
    if len(handed_parts) == len(parts) and all(s.status == "done" for s in st.scripts):
        st.status = "tune" if st.targets_open else "wrap-up"
    if plan_differs(project, st.n, data):
        st.plan_changed = True
        item = texts.plan_changed(st.n, project.plan_path(st.n).name)
        st.problems.append(item)
        st.open_items.append(item)
    for s in st.scripts:
        st.open_items += s.open_items()
        st.problems += s.problems()
    st.open_items += [texts.part_not_handed(i, p.get("name", "")) for i, p in enumerate(parts)
                      if i not in handed_parts]
    st.open_items += _stray_todos(project, plan_scripts)
    st.open_items += [texts.owner_mark_left(p) for p in scan.owner_marks(project)]
    st.open_items += suite_items(project, data)
    st.open_items += [texts.target_open(t) for t in st.targets_open]
    st.wrap_items = _wrap_items(project, st.n, plan, data)
    st.open_items += st.wrap_items
