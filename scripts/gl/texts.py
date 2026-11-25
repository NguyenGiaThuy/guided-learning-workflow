"""All user-visible text of the plugin. Later tasks add their own constants here."""


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


def result_empty(file):
    return "%s holds no test results." % file


def result_nothing_run(file):
    return "Nothing was run: every test in %s was skipped." % file


def result_unknown_suite(suite, known):
    return "Unknown test suite %s. Known suites: %s." % (suite, ", ".join(known) or "none")


def result_unreadable(file, detail):
    return "%s cannot be read: %s" % (file, detail)


# --- commands and the line that ends every status -------------------------------------

# key: command name without the slash; value: (step, argument hint, description).
# The hints and descriptions are the table "Descriptions" of docs/design.md, word for word.
COMMANDS = {
    "setup-learning": ("step 0: once per game", "",
                       "Step 0, once per game: set up guided learning in this project."),
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


def wrong_branch(expected, current):
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


def already_started(n, status):
    return "Phase %s was started already. Its status: %s." % (n, status)


def planning_started(n, plan, md):
    return ("Phase %s is being planned. No code is written in this step.\n"
            "Plan it with the owner and fill in %s: concepts, owner scripts (3 to 5, each with path, concept, "
            "TODO numbers and tests), parts with tasks, balance targets (measure, settings, min or max) and "
            "wrap-up questions with points. Decisions go to \"Notes for later\" in %s.\n"
            "The owner accepts the plan with /approve-phase %s, which checks that all of this is there."
            % (n, plan, md, n))


def carried_concept(name):
    return "Weak concept: %s" % name


def carried_differently(text):
    return "To do differently: %s" % text


def cannot_in_status(command, n, status):
    return "/%s does nothing for phase %s now: its status is %s." % (command, n, status)


def plan_incomplete(name):
    return "The plan is not complete. Missing or wrong in %s:" % name


GAP_NO_CONCEPT = "No concept."
GAP_NO_TARGET = "No balance target."
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


# --- records and the command line ----------------------------------------------------------------

TWEAKS_USED = "The 6 rounds of tuning are used. Write a reason for each target that is still missed."
NO_PROJECT = "Guided learning is not set up here. The owner sets it up with /setup-learning."
CLI_USAGE = """Use one of:
  learning.py status [N]
  learning.py log <kind> key=value ... [phase=N]
  learning.py record-tests <suite> <file> [phase=N]
  learning.py hand-over [N]
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


# --- the status line of SessionStart --------------------------------------------------------

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


def score_balance(met, total):
    return "Balance: %d/%d targets met." % (met, total)


def score_explain(ratings):
    return "Explain: " + "; ".join("%s: %s" % (name, rating) for name, rating in ratings.items()) + "."


def score_process(surprised, differently):
    return "Process: Surprised me: %s | Differently: %s" % (surprised or "-", differently or "-")


def last_phase(value):
    return "(last phase: %s)" % value
