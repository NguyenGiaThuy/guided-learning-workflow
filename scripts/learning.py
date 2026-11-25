import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", newline="\n")

from gl import commands, log, project, results, store, texts, version  # noqa: E402


class Refused(Exception):
    """A command line that cannot be carried out, in words for the user."""


def _project():
    found = project.find(os.getcwd())
    if found is None:
        raise Refused(texts.NO_PROJECT)
    return found.active


def _phase(argument, command):
    """The phase number of an argument; None if it is empty."""
    n, rest = commands.split_argument(argument)
    if n is None and not rest:
        return None
    if n is None or n < 1 or rest:
        raise Refused(texts.cli_bad_number(argument, command))
    return n


def _fields(args):
    found = {}
    for arg in args:
        key, equals, value = arg.partition("=")
        if not equals or key in found:
            raise Refused(texts.cli_bad_field(arg))
        found[key] = value
    return found


def _status(args):
    target = _project()
    argument = " ".join(args)
    out = commands.run(target, "summarize", argument)
    nothing_yet = not target.phase_numbers() and (not argument.strip() or commands.split_argument(argument)[0])
    return out.ok or bool(nothing_yet), out.text


def _log(args):
    if not args:
        raise Refused(texts.CLI_USAGE)
    target = _project()
    fields = _fields(args[1:])
    n = _phase(fields.pop("phase", ""), "log")
    return True, log.add(target, n, args[0], **fields)


def _record_tests(args):
    target = _project()
    if len(args) < 2:
        raise Refused(texts.CLI_USAGE)
    fields = _fields(args[2:])
    n = log.phase_for(target, _phase(fields.pop("phase", ""), "record-tests"))
    if fields:
        raise Refused(texts.CLI_USAGE)
    tests = results.record(target, n, args[0], args[1], log.check_open(n))
    return True, texts.tests_recorded(args[0], list(tests.values()))


def _hand_over(args):
    target = _project()
    out = commands.hand_over(target, _phase(" ".join(args), "hand-over"))
    return out.ok, out.text


def _version(args):
    return True, "%s %s" % (version.VERSION, version.plugin_hash())


SUBCOMMANDS = {"status": _status, "log": _log, "record-tests": _record_tests, "hand-over": _hand_over,
               "version": _version}


def main(argv):
    command = SUBCOMMANDS.get(argv[0]) if argv else None
    try:
        if command is None:
            raise Refused(texts.CLI_USAGE)
        ok, text = command(argv[1:])
    except (Refused, log.LogError, results.ResultError, store.BadJson, store.LockTimeout, OSError) as e:
        ok, text = False, str(e)
    sys.stdout.write(text + "\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
