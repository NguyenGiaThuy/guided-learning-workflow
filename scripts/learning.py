import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", newline="\n")

from gl import commands, hooks, log, project, rehearsal, results, setup, store, texts, version  # noqa: E402

SETUP_FLAG = "--claude-md"


class Refused(Exception):
    """A command line that cannot be carried out, in words for the user."""


def _outer():
    """The project of this folder, with its rehearsal as the switch wants it."""
    found = project.find(os.getcwd())
    if found is None:
        raise Refused(texts.NO_PROJECT)
    rehearsal.sync(found)
    return found


def _project():
    return _outer().active


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


def _from_input(fields):
    """Replace a value "-" by the text of stdin, so that the owner's words do not pass through a shell."""
    names = [k for k, v in fields.items() if v == "-"]
    if len(names) > 1:
        raise Refused(texts.log_one_stdin(names))
    for name in names:
        try:
            text = sys.stdin.buffer.read().decode("utf-8-sig")
        except UnicodeDecodeError:
            raise Refused(texts.log_stdin_not_utf8(name))
        fields[name] = text[:-1].rstrip("\r") if text.endswith("\n") else text


def _status(args):
    if project.find(os.getcwd()) is None:   # no error: a failed `!` command keeps the AI from seeing the text
        return True, texts.NO_PROJECT
    outer = _outer()
    argument = " ".join(args)
    out = rehearsal.run(outer, "summarize-phase", argument, watch=False)
    nothing_yet = not outer.active.phase_numbers() and (not argument.strip() or commands.split_argument(argument)[0])
    return out.ok or bool(nothing_yet), out.text


def _log(args):
    if not args:
        raise Refused(texts.CLI_USAGE)
    target = _project()
    fields = _fields(args[1:])
    n = _phase(fields.pop("phase", ""), "log")
    _from_input(fields)
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
    out = rehearsal.hand_over(_outer(), _phase(" ".join(args), "hand-over"))
    return out.ok, out.text


def _rehearse(args):
    return True, rehearsal.command(_outer(), args)


def _setup(args):
    paths = [a for a in args if a != SETUP_FLAG]
    if len(paths) != 1 or paths[0].startswith("--"):
        raise Refused(texts.CLI_USAGE)
    if not os.path.isfile(paths[0]):
        raise Refused(texts.setup_no_file(paths[0]))
    root = os.getcwd()
    found = project.find(root)
    if found and project.norm(found.root) != project.norm(root):
        raise Refused(texts.setup_elsewhere(found.root))
    own = project.norm(paths[0]) == project.norm(os.path.join(root, setup.PROJECT))
    done = setup.apply(root, store.read(paths[0]), claudeMd=SETUP_FLAG in args, own=own)
    try:
        done.append(commands.suggestion(_project()))
    except Exception:   # a broken phase file must not hide what was written; its own command reports it
        pass
    return True, "\n".join(done)


def _version(args):
    return True, "%s %s" % (version.VERSION, version.plugin_hash())


SUBCOMMANDS = {"status": _status, "log": _log, "record-tests": _record_tests, "hand-over": _hand_over,
               "setup": _setup, "rehearse": _rehearse, "version": _version}


def _hook(event):
    """Answer one hook call of Claude Code. Always exit code 0: the answer is in the output."""
    try:
        raw = sys.stdin.buffer.read()
    except Exception:   # no usable stdin is treated like broken JSON
        raw = b""
    out = hooks.answer(event, raw)
    if out:
        sys.stdout.write(out + "\n")
    return 0


def main(argv):
    if argv and argv[0] == "hook":
        return _hook(argv[1] if len(argv) > 1 else "")
    command = SUBCOMMANDS.get(argv[0]) if argv else None
    try:
        if command is None:
            raise Refused(texts.CLI_USAGE)
        ok, text = command(argv[1:])
    except (Refused, log.LogError, results.ResultError, setup.SetupError, rehearsal.RehearsalError, store.BadJson,
            store.LockTimeout, OSError) as e:
        ok, text = False, str(e)
    except Exception as e:   # the owner sees a message, never a traceback
        ok, text = False, texts.unexpected_error(e)
    sys.stdout.write(text + "\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
