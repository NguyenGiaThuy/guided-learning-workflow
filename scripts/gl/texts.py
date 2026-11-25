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
