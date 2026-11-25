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


# --- the status line of SessionStart --------------------------------------------------------

def hooks_line(version, code, rehearsal, run, problem):
    inner = "REHEARSAL run %s, %s %s" % (run, version, code) if rehearsal else "%s %s" % (version, code)
    line = "Learning hooks: on (%s)" % inner
    return line + " - " + problem if problem else line
