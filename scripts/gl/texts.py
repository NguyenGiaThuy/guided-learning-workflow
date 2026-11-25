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
