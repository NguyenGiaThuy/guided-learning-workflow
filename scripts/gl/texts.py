"""All user-visible text of the plugin. Later tasks add their own constants here."""
import json
from collections import namedtuple

# The words of a project (project.json "words"): what it is called, and the word before "targets".
Words = namedtuple("Words", "project targets")
DEFAULT_WORDS = Words("game", "balance")


def capitalized(word):
    """A word of the owner at the start of a sentence: only its first letter changes."""
    return word[:1].upper() + word[1:]


def bad_json(file, line, detail):
    return "%s is not valid JSON (line %d): %s" % (file, line, detail)


def bad_encoding(file, line):
    return "%s is not UTF-8 text (line %d). Save it as UTF-8." % (file, line)


def not_an_object(file):
    return "%s must hold one JSON object, written as { ... }." % file


def lock_timeout(path):
    return "%s is being written by another process; try again in a moment." % path


def config_problem(file, detail):
    return ("%s is not usable (%s), so rehearsal is off. "
            "Write {\"rehearsal\": true} or {\"rehearsal\": false}." % (file, detail))


def result_xml_broken(file, detail):
    return "%s is not readable test result XML: %s" % (file, detail)


def result_unknown_format(file):
    return ("%s is not a known test result file. Use NUnit 3 XML, JUnit XML, "
            "or lines like name,pass or name,fail." % file)


def result_bad_line(file, line):
    return "%s line %d is not of the form name,pass or name,fail." % (file, line)


_SMOKE_TEST = "A suite needs at least one test that runs. If it has none, add a smoke test."


def result_empty(file):
    return "%s holds no test results. %s" % (file, _SMOKE_TEST)


def result_nothing_run(file):
    return "Nothing was run: every test in %s was skipped. %s" % (file, _SMOKE_TEST)


def result_unknown_suite(suite, known):
    return "Unknown test suite %s. Known suites: %s." % (suite, ", ".join(known) or "none")


def result_unreadable(file, detail):
    return "%s cannot be read: %s" % (file, detail)


# --- commands and the line that ends every status -------------------------------------

# key: command name without the slash; value: (step, argument hint, description).
# The hints and descriptions are the table "Descriptions" of docs/design.md, word for word.
COMMANDS = {
    "setup-learning": ("step 0: once per project", "",
                       "Step 0, once per project: set up guided learning in this project."),
    "start-phase": ("step 1: plan with the AI", "<N> [skip: reason]",
                    "Step 1: begin PLANNING phase N with the AI. Checks that the phase before it is "
                    "finished. Writes no code."),
    "approve-phase": ("step 2: accept the plan", "<N> [change: reason]",
                      "Step 2: you ACCEPT the plan of phase N and lock its targets. Writes no code."),
    "build-phase": ("step 3: the AI builds", "[N]",
                    "Step 3: the AI WRITES the boilerplate (TODO shells, tests, the rest), or resumes it."),
    "summarize-phase": ("step 4: your turn", "[N]",
                        "Step 4: YOUR TURN. Shows your progress and resumes your coding, tuning and wrap-up."),
    "finish-phase": ("step 5: close the phase", "<N>",
                     "Step 5: CLOSE phase N. Checks that everything is done."),
}


def next_line(command, n):
    step = COMMANDS[command][0]
    return "Next: /%s%s  (%s)" % (command, "" if n is None else " %s" % n, step)


# --- status of a phase -------------------------------------------------------------------

DETACHED = "(detached HEAD)"
WHY = {"old": "results are older than the code: run the tests",
       "not run": "a test has no result yet: run the tests"}


def phase_header(n, status):
    return "Phase %s - %s" % (n, status)


def todos_count(done, total):
    return "%d of %d TODOs done" % (done, total)


def targets_count(met, total):
    return "%d of %d %s" % (met, total, "target" if total == 1 else "targets")


def then_line(steps):
    return "Then: " + ", ".join(steps)


def ai_turn(part, parts, name):
    return ("It is the AI's turn (part %d of %d%s). There is nothing for you to code until it "
            "hands the part over." % (part + 1, parts, ": " + name if name else ""))


def owner_turn(part, parts):
    return "Your turn (part %d of %d)." % (part + 1, parts)


def wrong_branch(expected, current, simulated=False):
    if simulated:
        return ("Wrong branch: this phase is on %s, but %s is checked out (simulated). Switch with: "
                "learning.py rehearse branch %s" % (expected, current, expected))
    if current == DETACHED:
        return ("Wrong branch: this phase is on %s, but no branch is checked out (detached HEAD). "
                "Switch with: git switch %s" % (expected, expected))
    return ("Wrong branch: this phase is on %s, but %s is checked out. Switch with: git switch %s"
            % (expected, current, expected))


def planning_text(n):
    return "The plan of phase %s is being written. Nothing is built yet." % n


def done_text(n):
    return "Phase %s is done." % n


def skipped_text(n, reason):
    return "Phase %s was skipped%s." % (n, ": " + reason if reason else "")


def open_heading():
    return "Still open:"


STATUS = {"done": "done", "not started": "not started", "unknown": "unknown",
          "in progress": "in progress"}
WRAP_UP = "wrap-up"


def todos_of(done, total):
    return "%d of %d" % (done, total)


def tests_cell(passed, total):
    return "tests %d/%d" % (passed, total)


def help_note(level):
    return "help: %d" % level


def next_note(todo):
    return "<- next: TODO %s" % todo


def failing_note(names):
    return "failing: " + ", ".join(names)


def tune_step(met, total):
    return "tune (%s)" % targets_count(met, total)


def bullet(item):
    return "  - " + item


def plan_missing(name):
    return "%s is missing or empty, so there is nothing to build." % name


def script_label(sid, name):
    return "Owner %s %s" % (sid, name)


# --- open items (sentences) --------------------------------------------------------------

def todos_left(label, count):
    return "%s: %d TODO%s left." % (label, count, "" if count == 1 else "s")


def tests_failing(label, names):
    return "%s: failing tests: %s." % (label, ", ".join(names))


def tests_not_run(label, names):
    return "%s: tests with no result yet: %s. Run the tests." % (label, ", ".join(names))


def tests_old(label):
    return "%s: the test results are older than the code. Run the tests again." % label


def owner_mark_left(place):
    return "The owner mark is still at %s. Remove it when the test passes." % place


def suite_not_recorded(suite):
    return "Suite %s has no recorded results." % suite


def suite_old(suite):
    return "Suite %s: the recorded results are older than the code." % suite


def suite_failing(suite, names):
    return "Suite %s has failing tests: %s." % (suite, ", ".join(names))


def suite_not_run(suite, names):
    shown = ", ".join(names[:5]) + (" and %d more" % (len(names) - 5) if len(names) > 5 else "")
    return ("Suite %s: %d test%s not run since the last code change: %s. Run the whole suite and record it. "
            "A test that was removed or renamed must be gone from the code. An ignored test is seen when the result "
            "file of the whole suite reports it." % (suite, len(names), "" if len(names) == 1 else "s", shown))


def target_open(target):
    return "Target %s has no measured value in range and no written reason." % target


def script_file_missing(label, path):
    return "%s: the file %s is missing." % (label, path)


def lost_todo(todo, label, path):
    return ("%s: TODO %s was never in %s, or was removed before the hand-over. "
            "Ask the AI to restore it with /build-phase." % (label, todo, path))


def part_label(part, name):
    return "Part %d%s" % (part + 1, " (%s)" % name if name and name != "Part %d" % (part + 1) else "")


def part_not_handed(part, name):
    return "%s is not handed over yet." % part_label(part, name)


def todo_elsewhere(todo, path):
    return "TODO(owner %s) is left in %s." % (todo, path)


def plan_not_approved(n):
    return "The plan of phase %s is not approved yet." % n


def plan_changed(n, name):
    return ("%s was changed after it was approved. Put it back, or accept the change with "
            "/approve-phase %s change: <reason>" % (name, n))


ON_MY_OWN = "on my own"
WITH_HELP = "with help"
CANT_YET = "can't yet"


def answer_missing(concept):
    return "Concept %s: no planned question is answered." % concept


def rating_missing(concept):
    return "Concept %s: no rating of at least \"with help\"." % concept


def summary_missing(concept):
    return "Concept %s: no entry in the concept summary." % concept


def lessons_count(count):
    return "Lessons: %d written, 3 to 5 are needed." % count


SURPRISED_MISSING = "Process: \"Surprised me:\" is empty."
DIFFERENTLY_MISSING = "Process: \"Differently:\" is empty."


# --- commands: refusals and replies ----------------------------------------------------------

NO_PHASE_YET = "There is no phase yet. Begin with /start-phase 1."
CARRIED_HEADING = "Carried over from the phase before:"


def usage(command):
    return "Use it as: /%s %s" % (command, COMMANDS[command][1])


def bad_number(argument, command):
    if not argument:
        return "Which phase? " + usage(command)
    return "\"%s\" is not a phase number (1, 2, 3 ...). %s" % (argument, usage(command))


def no_phase(n, known):
    return "Phase %s does not exist. Phases: %s. A new phase begins with /start-phase." % (
        n, ", ".join(str(k) for k in known) or "none yet")


def skip_command(n):
    return "/start-phase %s skip: <reason>" % n


def skip_needs_reason(n):
    return "A skip needs a reason: %s" % skip_command(n)


def previous_missing(n):
    return ("Phase %s has no file in the project, so phase %s cannot start. If it was done without this "
            "workflow, or is left out: %s" % (n - 1, n, skip_command(n)))


def previous_open(n):
    return "Phase %s cannot start: phase %s is not finished. To leave it: %s" % (n, n - 1, skip_command(n))


def previous_not_merged(n, branch):
    return ("Phase %s is done, but its branch %s is not merged. Merge it, check out the branch to go on "
            "from, and type /start-phase %s again. To go on without: %s" % (n - 1, branch, n, skip_command(n)))


def done_not_merged(n, branch, following=None, later=None):
    """following: the phase to start after the merge, if it is not the next one.
    later: (number, branch) of a phase that was started already; then there is none to start."""
    if later:
        way_on = "Phase %s was started after it, on branch %s. To go on: git switch %s" % (later + later[1:])
    else:
        following = following or n + 1
        way_on = ("Merge %s, and then type /start-phase %s. To go on without merging: git switch %s, and there type %s"
                  % (branch, following, branch, skip_command(following)))
    return ("Phase %s is done on branch %s, not merged into what is checked out here. %s. To look at phase %s before "
            "the merge: git switch %s" % (n, branch, way_on, n, branch))


def phase_files_uncommitted(n, names):
    return ("Files of phase %s have changes that are not committed: %s. Commit them first, on the branch of the phase."
            % (n, ", ".join(names)))


def already_started(n, status):
    return "Phase %s was started already. Its status: %s." % (n, status)


def planning_started(n, plan, md, words, tuning):
    targets = ", %s targets (measure, settings, min or max)" % words.targets if tuning else ""
    return ("Phase %s is being planned. No code is written in this step.\n"
            "Plan it with the owner and fill in %s: concepts, owner scripts (3 to 5, each with path, concept, "
            "TODO numbers and tests), parts with tasks%s and "
            "wrap-up questions with points. Decisions go to \"Notes for later\" in %s.\n"
            "The owner accepts the plan with /approve-phase %s, which checks that all of this is there."
            % (n, plan, targets, md, n))


def carried_concept(name):
    return "Weak concept: %s" % name


def carried_differently(text):
    return "To do differently: %s" % text


def cannot_in_status(command, n, status):
    return "/%s does nothing for phase %s now: its status is %s." % (command, n, status)


def plan_incomplete(name):
    return "The plan is not complete. Missing or wrong in %s:" % name


GAP_NO_CONCEPT = "No concept."
def gap_no_target(words):
    return "No %s target." % words.targets


GAP_NO_PART = "No part."
_SCRIPT_KEYS = {"path": "a path", "concept": "a concept", "todos": "a list of TODO numbers as text, like \"1.1\"",
                "tests": "a list of test names"}
_TARGET_KEYS = {"measure": "how it is measured (measure)", "settings": "a list of settings that influence it"}


def gap_list(key):
    return "\"%s\" must be a list of objects." % key


def gap_id(key):
    return "An entry of \"%s\" has no id." % key


def gap_concept_name(concept):
    return "Concept %s: needs a name." % concept


def gap_script_id(sid):
    return "Script id %s must be a number." % sid


def gap_duplicate(key, i):
    return "Id %s is there more than once in %s." % (i, key)


def gap_script_count(count):
    return "%d owner scripts; a phase has 1 to 5 (3 to 5 is best)." % count


def gap_script(label, key):
    return "%s: needs %s." % (label, _SCRIPT_KEYS[key])


def gap_script_path(label, path, folders, extensions):
    return ("%s: the path %s must begin in a code folder of project.json (%s), without \"..\", and end with %s."
            % (label, path, ", ".join(folders), " or ".join(extensions)))


def gap_unknown_concept(label, concept):
    return "%s: concept %s is not in the plan." % (label, concept)


def gap_todo(label, todo):
    return "%s: TODO number %s must be <script id>.<step>." % (label, todo)


def gap_parts(label, count):
    return "%s: must be in exactly one part, but is in %s." % (label, count or "none")


def gap_part_tasks(label):
    return "%s: needs a list of tasks." % label


def gap_part_scripts(label):
    return "%s: \"scripts\" must be a list of script ids." % label


def gap_part_script(label, sid):
    return "%s: script %s is not in the plan." % (label, sid)


def gap_target(target, key):
    return "Target %s: needs %s." % (target, _TARGET_KEYS[key])


def gap_target_range(target):
    return "Target %s: needs a range: min or max or both, as numbers, with min not above max." % target


def gap_question(concept):
    return "Concept %s: needs a wrap-up question." % concept


def gap_points(question):
    return "Question %s: needs a list of points the answer must contain." % question


def approved(n):
    return "The plan of phase %s is accepted and locked. Nothing is built yet." % n


def few_scripts_note(count):
    return "Note: the plan has %d owner script%s. 3 to 5 is the advice." % (count, "" if count == 1 else "s")


def approved_already(n):
    return "The plan of phase %s is approved already, and it was not changed." % n


def nothing_changed(n):
    return "The plan of phase %s was not changed since it was approved, so there is nothing to accept." % n


def change_needs_reason(n):
    return "A change of the plan needs a reason: /approve-phase %s change: <reason>" % n


def change_accepted(n):
    return "The changed plan of phase %s is accepted, and the reason is recorded." % n


def handed_changed(n):
    return ("A part of phase %s that is handed over cannot change any more. Put this back, and plan new work "
            "in a new part after it:" % n)


def handed_added(label):
    return "%s was added." % label


def handed_removed(label):
    return "%s was removed." % label


def handed_path(label, before, now):
    return "%s: the path was changed from %s to %s." % (label, before, now)


def handed_todo_added(label, todo):
    return "%s: TODO %s was added." % (label, todo)


def handed_todo_removed(label, todo):
    return "%s: TODO %s was removed." % (label, todo)


def build_is_over(n, status):
    return "Everything of phase %s is built: it is in %s." % (n, status)


def owners_turn(n, part):
    return "It is the owner's turn in phase %s, part %d, so the AI does not build." % (n, part + 1)


def build_heading(n, part, parts, name):
    return "Phase %s, part %d of %d%s: it is the AI's turn. The tasks:" % (
        n, part + 1, parts, " (%s)" % name if name else "")


def task_line(index, task, done):
    return "  %d. [%s] %s" % (index + 1, "done" if done else "open", task)


SCRIPTS_HEADING = "The owner scripts of this part, written as shells:"


def script_line(label, path, todos, tests):
    return "  %s  %s  TODOs %s  tests %s" % (label, path, ", ".join(str(t) for t in todos),
                                            ", ".join(str(t) for t in tests))


def build_rules(n, part):
    return ("Go on with the first open task. After each task: learning.py log task phase=%s part=%d index=<number>. "
            "When all are done: learning.py hand-over %s. Do not write the code of the owner's TODOs."
            % (n, part + 1, n))


def no_hand_over(n):
    return "Phase %s has nothing to hand over: it is not the AI's turn in a build." % n


def hand_over_refused(n, part):
    return "Phase %s, part %d is not handed over. Missing:" % (n, part + 1)


def todo_not_in_shell(label, todo, path):
    return "%s: TODO(owner %s) is not in %s." % (label, todo, path)


def test_not_in_code(label, test):
    return "%s: test %s is not in the test code." % (label, test)


def owner_test_not_run(label, test):
    return "%s: test %s has no result since the last code change. Run it; it must fail." % (label, test)


def owner_test_passes(label, test):
    return "%s: test %s passes already, so it does not test what the owner writes." % (label, test)


def _count(n, word):
    return "%d %s%s" % (n, word, "" if n == 1 else "s")


def handed_over(n, part, scripts, todos):
    text = "Phase %s, part %d handed over." % (n, part + 1)
    if scripts:
        text += " Your turn: %s, %s." % (_count(scripts, "script"), _count(todos, "TODO"))
    return text


def next_in_new_chat(command, n, first=""):
    return "Next: %sopen a new chat and type /%s %s" % (first, command, n)


def not_finished(n):
    return "Phase %s cannot be closed yet." % n


def still_in(status):
    return "The phase is still in %s." % status


def closing_done(n, path):
    return "Phase %s is done. Saved in %s." % (n, path)


def closing_branch(branch, merged):
    return "Branch %s: %s." % (branch, "merged" if merged else "not merged")


def closing_carried(n, weak, differently):
    return "Carried to phase %s: %s | %s" % (n, ", ".join(weak) or "no weak concept", differently or "nothing")


MERGE_FIRST = "merge the branch, then "
COMMIT_FIRST = "commit, "   # closing has just changed the phase files


def closing_first(commit, merge):
    """What the owner does before the new chat of the next phase."""
    return (COMMIT_FIRST + MERGE_FIRST if merge else COMMIT_FIRST + "then ") if commit else ""


# --- records and the command line ----------------------------------------------------------------

TWEAKS_USED = "The 6 rounds of tuning are used. Write a reason for each target that is still missed."
NO_PROJECT = "Guided learning is not set up here. The owner sets it up with /setup-learning."
CLI_USAGE = """Use one of:
  learning.py status [N]
  learning.py log <kind> key=value ... [phase=N]   (key=- reads the value from the input)
  learning.py record-tests <suite> <file> [phase=N]
  learning.py hand-over [N]
  learning.py setup <settings.json> [--claude-md]
  learning.py rehearse pass | fail | merge | branch [name] | check <id> | report
  learning.py version"""


def unexpected_error(error):
    """One line for an exception nobody foresaw, for example a plan edited by hand with wrong types."""
    return "guided-learning error: %s: %s" % (type(error).__name__, " ".join(str(error).split()))


def cli_bad_number(argument, command):
    return "%s: \"%s\" is not a phase number (1, 2, 3 ...)." % (command, argument)


def cli_bad_field(arg):
    return "\"%s\" must be key=value, with each key once." % arg


def log_unknown_kind(kind, kinds):
    return "Unknown kind of record: %s. Known: %s." % (kind, ", ".join(kinds))


def log_fields(kind, fields, missing, unknown):
    text = "A record of kind %s has the fields %s." % (kind, ", ".join(fields))
    if missing:
        text += " Missing: %s." % ", ".join(missing)
    if unknown:
        text += " Unknown: %s." % ", ".join(unknown)
    return text


def log_one_stdin(names):
    return "Only one field can be read from the input, not %s." % " and ".join(names)


def log_stdin_not_utf8(name):
    return "The input for %s is not UTF-8 text." % name


def log_empty(name):
    return "%s must not be empty." % name


def log_not_whole(name, value):
    return "%s must be a whole number, not \"%s\"." % (name, value)


def log_not_number(name, value):
    return "%s must be a number, not \"%s\"." % (name, value)


def log_choice(name, value, allowed):
    return "%s must be one of: %s. Not \"%s\"." % (name, ", ".join(allowed), value)


def log_unknown(name, value, ids):
    return "There is no %s \"%s\" in the plan. Known: %s." % (name, value, ", ".join(str(i) for i in ids) or "none")


def log_no_task(part, index):
    return "The plan has no task %s in part %s." % (index, part)


def no_record(n, status):
    return "Phase %s is in status %s. Records are only added between /approve-phase and /finish-phase." % (n, status)


def recorded(kind):
    return "Recorded: %s." % kind


def task_recorded(part, index):
    return "Recorded: task %d of part %d is done." % (index + 1, part + 1)


def tweak_recorded(rounds, limit, predicted, actual, right):
    return "Recorded: tweak %d of %d. Predicted %s, result %s: %s." % (
        rounds, limit, predicted, actual, "right" if right else "wrong")


def tests_recorded(suite, outcomes):
    return "Recorded for suite %s: %d passed, %d failed." % (suite, outcomes.count("passed"), outcomes.count("failed"))


# --- hooks ------------------------------------------------------------------------------------------

HOOK_INPUT = "the hook input is not a JSON object."
HOOK_NO_PATH = "the hook input names no file."
HOOK_SNAPSHOT = "the list of files from before this tool call is not readable."


def hook_error(message):
    return "guided-learning error: %s" % message


def refused_locked(path, n):
    return ("%s is locked: in phase %s the owner writes it. Do not edit it by any other route. "
            "Help the owner with hints or a review instead (/summarize-phase %s)." % (path, n, n))


def refused_locked_elsewhere(path, n, branch):
    return ("%s is locked: the owner writes it in phase %s, which is open on the branch %s. Do not edit it by any other "
            "route. Tell the owner that another branch is checked out." % (path, n, branch))


def refused_state(path):
    return ("%s is written only by the script. Use learning.py log, record-tests or hand-over instead." % path)


def refused_plan(path, n):
    return ("%s is approved and locked. Tell the owner what should change: the owner edits it by hand and "
            "accepts it with /approve-phase %s change: <reason>" % (path, n))


def refused_settings(path):
    return "%s belongs to the owner. Tell the owner what should change; the owner edits it by hand." % path


def refused_local(path):
    return "%s holds the records of the learning script. Leave it alone." % path


def refused_code_planning(path, n):
    return ("%s is code, and phase %s is still being planned. Finish the plan with the owner. The owner accepts it "
            "with /approve-phase %s and then starts the work with /build-phase %s." % (path, n, n, n))


def refused_code_unbuilt(path, n):
    return ("%s is code, and the work on phase %s has not started. Wait until the owner types /build-phase %s."
            % (path, n, n))


def refused_todo(path, ids):
    return ("This edit of %s removes %s. Leave it there: the owner replaces it with their own code. If it should "
            "not be there at all, ask the owner to remove it."
            % (path, ", ".join("TODO(owner %s)" % i for i in ids)))


def files_changed_owner(names):
    return ("Files of the learning workflow changed while a tool ran: %s. If that was you, carry on. "
            "The AI is asked to check with you; nothing was undone." % ", ".join(names))


def files_changed_ai(names):
    return ("Owner or workflow files changed while this tool ran: %s. Ask the owner whether it was them before "
            "you do anything else." % ", ".join(names))


def closing_asked(text):
    return "End your answer with exactly this text, word for word, on lines of its own:\n" + text


# --- the status line of SessionStart --------------------------------------------------------

HOOKS_NOT_SEEN = ("Learning hooks: not running in this chat. Nothing is checked or refused. Open a new chat; if "
                  "this line stays, see \"What is not guaranteed\" in the README of the plugin.")


def hooks_line(version, code, rehearsal, run, problem):
    inner = "REHEARSAL run %s, %s %s" % (run, version, code) if rehearsal else "%s %s" % (version, code)
    line = "Learning hooks: on (%s)" % inner
    return line + " - " + problem if problem else line


# --- the scorecard and the done status -----------------------------------------------------------

NOT_RATED = "not rated"
NO_HELP = "none"
SUMMARY_HEADING = "Concept summary:"
LESSONS_HEADING = "Lessons:"
SCORECARD_SECTION = "## Scorecard"


def scorecard_heading(n):
    return "Scorecard of phase %s" % n


def score_build(passing, total, helps):
    shown = ", ".join("%s %s" % (label, level or NO_HELP) for label, level in helps.items())
    return "Build: %d/%d owner scripts pass their tests. Highest help level: %s." % (passing, total, shown or NO_HELP)


def score_predict(right, total):
    return "Predict: %d/%d tweaks had the right predicted direction." % (right, total)


def score_balance(met, total, words):
    return "%s: %d/%d targets met." % (capitalized(words.targets), met, total)


def score_explain(ratings):
    return "Explain: " + "; ".join("%s: %s" % (name, rating) for name, rating in ratings.items()) + "."


def score_process(surprised, differently):
    return "Process: Surprised me: %s | Differently: %s" % (surprised or "-", differently or "-")


def last_phase(value):
    return "(last phase: %s)" % value


# --- setup ----------------------------------------------------------------------------------------

SETUP_GIVEN = "The settings"
def setup_settings_by_hand(words):
    return ("This %s was set up before, so its own settings count. To change one, the owner edits "
            ".claude/learning/project.json by hand." % words.project)


SETUP_SECTION_ADDED = "Added to CLAUDE.md: the section of guided learning."
SETUP_SECTION_THERE = "CLAUDE.md has the section of guided learning already and was not changed."
_SETUP_KEYS = {
    "docs": "a folder of the {project} for the phase files, like \"Docs/learning\", and not in .claude",
    "code": "a list of code folders of the {project}, like [\"src\"]",
    "extensions": "a list of file extensions of the code, like [\".cs\"]",
    "ownerMark": "the text in the code that marks an owner test, on one line",
    "suites": "a list of names of test suites, like [\"Unit\"]",
    "background": "a text about the owner's experience",
    "domain": "the field of the project in the owner's words, on one line, at most 100 characters",
    "words": ("an object with \"project\" and \"targets\", like {\"project\": \"app\", \"targets\": \"performance\"}: "
              "each one or two words of letters, digits or hyphens, starting with a letter or digit, at most 20 characters"),
    "tuning": "true or false",
}


def setup_key(key, given, words):
    must = _SETUP_KEYS[key].replace("{project}", words.project)
    return "\"%s\" is %s. It must be %s." % (key, "wrong" if given else "missing", must)


def setup_unknown(key):
    return "\"%s\" is no setting." % key


def unknown_settings(keys):
    shown = [json.dumps(k if len(k) <= 30 else k[:30] + "...", ensure_ascii=False) for k in keys[:3]]
    more = ["and %d more" % (len(keys) - 3)] if len(keys) > 3 else []
    return "No settings in project.json, without effect: %s." % ", ".join(shown + more)


def setup_refused(name):
    return "%s cannot be used. Nothing was written." % name


def setup_not_a_folder(folder):
    return "%s cannot be a folder, because a file is in the way. Nothing was written." % folder


def setup_no_file(path):
    return "There is no settings file %s." % path


def setup_elsewhere(root, words):
    return "This folder is inside the %s at %s, which is set up already. Run setup there." % (words.project, root)


def setup_written(name):
    return "Written: %s" % name


def setup_kept(name):
    return "%s is there already and was not changed." % name


def setup_lines_added(name, lines):
    return "Added to %s: %s" % (name, ", ".join(lines))


def setup_ignored(words):
    return ("Git ignores .claude/learning/project.json because of a line in .gitignore, so the settings would not "
            "be saved with the %s. Change that line. With .claude/ for example: write .claude/* and below it "
            "!.claude/learning/" % words.project)


def settings_wrong(file, problems):
    return "%s cannot be used. The owner mends it by hand: %s" % (file, " ".join(problems))


def setup_no_folder(folder):
    return "The code folder %s does not exist yet. Check that its name is right." % folder


# --- rehearsal ------------------------------------------------------------------------------------

REHEARSE_OFF = ("There is no rehearsal: the switch is off. The owner sets {\"rehearsal\": true} in "
                ".claude/learning/config.json.")
REHEARSE_USAGE = "Use it as: learning.py rehearse pass | fail | merge | branch [name] | check <id> | report"
REHEARSAL_NO_BRANCH = "No phase of the rehearsal has a branch, so there is nothing to merge."
SIM_PASS = "Simulated: all planned tests pass, after the last code change."
SIM_FAIL = "Simulated: the tests of the scripts that are not done fail, all others pass."
BY = {"script": "seen by the script", "owner": "checked by the owner"}


def rehearsal_planning(n):
    return ("Phase %s: the files are made. Planning would start here. This is a rehearsal, so nothing is planned: "
            "show this text and stop." % n)


def rehearsal_short(run, words):
    return "REHEARSAL run %s. This is the fake project, not your %s." % (run, words.project)


def rehearsal_rules(run, script, words):
    return ("REHEARSAL run %s. The project is the folder .claude/learning/rehearsal: every path below is inside it, "
            "also the settings in .claude/learning/project.json. Branch, merge and test results are simulated, with: "
            "bash \"%s\" rehearse pass | fail | merge | branch [name]. The AI runs that, and \"rehearse "
            "check <id>\", only when the owner says so. Run no tests, use no git, and leave the real %s alone."
            % (run, script, words.project))


def rehearsal_not_usable(path):
    return ("%s is a link, or not a folder, or lies behind a link. The rehearsal is made only in a real folder there, "
            "so nothing was touched. Move it away, or set the switch in config.json to false." % path)


def rehearsal_real_folder(folder, path):
    return ("%s is named in project.json and lies in %s, which the rehearsal would delete. Nothing was touched. "
            "Set the switch in config.json to false." % (folder, path))


def rehearsal_no_template(path):
    return "The template of the rehearsal is missing in %s. Install the plugin again." % path


def rehearsal_no_build(n, status):
    return "Test results are simulated only in status build. Phase %s is in status %s." % (n, status)


def sim_branch(branch):
    return "Simulated: the branch %s is checked out." % branch


def sim_merged(branch):
    return "Simulated: the branch %s is merged." % branch


def unknown_check(check, known):
    return "There is no check \"%s\" in the checklist. Known: %s." % (check, ", ".join(known))


def script_ticks(check):
    return "%s is ticked by the script when it sees it, not by the owner." % check


def ticked(check, by):
    return "Ticked: %s, %s." % (check, BY[by])


def tick_failed(error):
    return "Note: the rehearsal could not write its report (%s). The command itself is not affected." % error


def report_title(run):
    return "Rehearsal run %s" % run


def report_about(started, version, code):
    return "Started: %s. Plugin: %s %s." % (started, version, code)


def report_count(done, total):
    return "Ticked: %d of %d." % (done, total)


def report_line(check, type_, tick):
    if tick is None:
        return "- [ ] %s - %s" % (check, type_)
    return "- [x] %s - %s (%s, %s)" % (check, type_, BY.get(tick.get("by"), tick.get("by")), tick.get("time"))


CHECK_GONE = "no longer in the checklist"


def compare_first(run):
    return "Rehearsal run %s: there is no earlier run to compare with." % run


def compare_heading(run, last):
    return "Rehearsal run %s compared with run %s:" % (run, last)


def compare_new(checks):
    return "Ticked now, but not in the last run: %s." % ", ".join(checks)


def compare_open(checks):
    return "Ticked in the last run, but not yet now: %s." % ", ".join(checks)


COMPARE_SAME = "The ticked checks are the same."
COMPARE_PLUGIN_SAME = "The plugin is unchanged."


def compare_plugin(before, now):
    return "The plugin changed: %s, before: %s." % (now, before)
