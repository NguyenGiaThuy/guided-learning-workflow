"""Repeat runs: start Claude Code many times in throwaway projects, and judge each run by files and output.

    python tests/repeat/run.py --model <m> --times 10 [--case name] [--mode mode]

It uses your Claude account. Exit code: 0 all passed, 1 something failed, 2 nothing failed but something was not run.
"""
import argparse
import json
import os
import platform
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
from collections import Counter
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import helpers  # noqa: E402,F401  (puts scripts/ on the path)
from gl import version  # noqa: E402
from repeat import cases  # noqa: E402
from repeat.cases import FAILED, NOT_RUN, PASSED, Run, Verdict  # noqa: E402

PREFIX = "gl-repeat-"
LIMIT = 120                  # seconds of one run
NO_MORE = "no more runs: "   # begins a note after which no further run makes sense


# --- what Claude Code is started with -----------------------------------------------------------------

def find_claude(given, env, home):
    """The program: the argument, CLAUDE_EXE, the path, or the newest one of the VS Code extension."""
    found = given or env.get("CLAUDE_EXE") or shutil.which("claude")
    if found:
        return str(found)
    name = re.compile(r"anthropic\.claude-code-(\d+(?:\.\d+)*)")
    inside = []
    for path in (Path(home) / ".vscode" / "extensions").glob("anthropic.claude-code-*/resources/native-binary/claude*"):
        match = name.match(path.parents[2].name)
        if match and path.name in ("claude", "claude.exe"):
            inside.append(([int(x) for x in match.group(1).split(".")], str(path)))
    return max(inside)[1] if inside else None


_KEEP = re.compile(r"CLAUDE_CONFIG_DIR|CLAUDE_CODE_OAUTH_TOKEN|CLAUDE_CODE_USE_\w+|CLAUDE_CODE_SKIP_\w+_AUTH|"
                   r"CLAUDE_CODE_GIT_BASH_PATH")
_WHO = {"NAME": "Repeat run", "EMAIL": "repeat@example.invalid"}


def clean_env(env):
    """The environment without what a surrounding Claude Code or git put there, so a run is a chat of its own."""
    kept = {k: v for k, v in env.items()
            if _KEEP.fullmatch(k.upper()) or not re.match(r"CLAUDE|AI_AGENT$|GIT_", k.upper())}
    for who in ("AUTHOR", "COMMITTER"):
        kept.update({"GIT_%s_%s" % (who, key): value for key, value in _WHO.items()})
    kept["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] = "1"
    return kept


def command_of(case, claude, model):
    """Only the plugin under test: no settings of the user, no other servers, and the chat is not kept."""
    command = [claude, "-p", "--plugin-dir", str(version.ROOT), "--model", model, "--permission-mode", case.mode,
               "--output-format", "stream-json", "--verbose", "--include-hook-events", "--no-session-persistence",
               "--setting-sources", "project,local", "--strict-mcp-config"] + case.options
    return command + ["--allowedTools=" + ",".join(case.allowed)] * bool(case.allowed)


# --- the throwaway project ---------------------------------------------------------------------------------

def make_game(case, folder, env):
    game = Path(folder) / "game"
    game.mkdir()
    case.build(game)
    for args in (["init", "-q"], ["symbolic-ref", "HEAD", "refs/heads/stage-2"], ["add", "-A"],
                 ["commit", "-q", "-m", "Lantern Keeper"]):
        subprocess.run(["git", "-c", "core.autocrlf=false", "-c", "commit.gpgsign=false"] + args, cwd=game, env=env,
                       check=True, capture_output=True)
    return game


def delete(folder):
    """Delete a folder of a run. git keeps read-only files, and a program may still hold one for a moment."""
    folder = Path(folder)
    if not folder.name.startswith(PREFIX):
        raise ValueError("not a folder of a repeat run: %s" % folder)

    def unlock(action, path, error):
        try:
            os.chmod(path, stat.S_IRWXU)
            action(path)
        except OSError:
            pass   # tried again below

    for _ in range(20):
        shutil.rmtree(folder, **{"onexc" if sys.version_info >= (3, 12) else "onerror": unlock})
        if not folder.exists():
            return
        time.sleep(0.5)
    print("Could not delete %s" % folder, file=sys.stderr)


# --- one start ---------------------------------------------------------------------------------------------

def read_events(path):
    """The events of a stream, without lines that are no JSON (a warning, or a line cut off)."""
    events = []
    for line in Path(path).read_bytes().decode("utf-8", errors="replace").split("\n"):
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def _kill(process):
    """Stop the program that was started, with its children, and nothing else."""
    if process.poll() is None:
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(process.pid)], capture_output=True)
        else:
            os.killpg(process.pid, signal.SIGKILL)   # a group of its own, see start()
    process.wait()


def _next_prompt(process, prompts, sent):
    """Send the next prompt, or say that there is none."""
    if sent < len(prompts):
        message = {"type": "user", "message": {"role": "user", "content": prompts[sent]}}
        process.stdin.write(json.dumps(message).encode("utf-8") + b"\n")
        process.stdin.flush()
    else:
        process.stdin.close()


def start(command, prompts, cwd, env, out, limit=LIMIT):
    """(events, stderr, timed out) of one run. Several prompts are sent one by one, each after the last answer."""
    several = len(prompts) > 1
    command = command + (["--input-format", "stream-json"] if several else ["--", prompts[0]])
    err = Path(str(out) + ".err")
    end = time.monotonic() + limit
    timed_out, sent = False, 0
    with open(out, "wb") as stdout, open(err, "wb") as stderr:
        process = subprocess.Popen(command, cwd=cwd, env=env, stdout=stdout, stderr=stderr,
                                   stdin=subprocess.PIPE if several else subprocess.DEVNULL,
                                   start_new_session=os.name != "nt")
        try:
            while process.poll() is None and not timed_out:
                if several and sent <= len(prompts):
                    if sum(e.get("type") == "result" for e in read_events(out)) >= sent:
                        try:
                            _next_prompt(process, prompts, sent)
                        except OSError:   # it ended meanwhile
                            break
                        sent += 1
                timed_out = time.monotonic() > end
                time.sleep(0.1)
        finally:
            _kill(process)
    return read_events(out), err.read_bytes().decode("utf-8", errors="replace").strip(), timed_out


# --- the outcome -------------------------------------------------------------------------------------------

_LIMIT, _LOGIN, _MODEL, _CONNECTION = (NO_MORE + "usage limit", NO_MORE + "not logged in",
                                       NO_MORE + "model not available", "no connection")
_WORDS = (
    (_LIMIT, r"(usage|session|weekly|rate|opus|sonnet) limit|hit your .*limit|limit reached|credit balance"),
    (_LOGIN, r"invalid api key|not logged in|please run /login|authenticat|oauth|\b401\b|\b403\b"),
    (_MODEL, r"issue with the selected model|model .*(not found|not available|not exist)"),
    (_CONNECTION, r"connection|unable to connect|econn|etimedout|enotfound|network|fetch failed|overloaded|"
                  r"api error: 5\d\d|internal server error|request timed out"),
)
_STATUS = {401: _LOGIN, 403: _LOGIN, 404: _MODEL, 429: _LIMIT}


def _reason_in(text):
    return next((reason for reason, words in _WORDS if re.search(words, text, re.I)), None)


def not_run_reason(events, stderr, timed_out):
    """Why a run says nothing about the plugin (connection, usage limit, login, model), or None.

    Only errors of Claude Code itself count, never the words of the AI.
    """
    if timed_out:
        rest = [e for e in events if e.get("type") in ("assistant", "user", "result") or e.get("subtype") == "api_retry"]
        if rest and rest[-1].get("subtype") == "api_retry":
            return _reason_in(str(rest[-1].get("error", "")).replace("_", " ")) or _CONNECTION
        return None
    result = next((e for e in reversed(events) if e.get("type") == "result"), None)
    if result is None:
        return None if events else _reason_in(stderr)
    if not result.get("is_error"):
        return None
    status = result.get("api_error_status")
    if isinstance(status, int) and (status in _STATUS or status >= 500):
        return _STATUS.get(status, _CONNECTION)
    if any((e.get("rate_limit_info") or {}).get("status") == "rejected" for e in events):
        return _LIMIT
    return _reason_in(str(result.get("result") or result.get("errors") or ""))


def verdict(case, run):
    reason = not_run_reason(run.events, run.stderr, run.timed_out)
    if reason:
        return Verdict(NOT_RUN, reason)
    begun = next((e for e in run.events if e.get("subtype") == "init"), None)
    if begun and begun.get("permissionMode") != case.mode:
        return Verdict(NOT_RUN, "mode %s is not available, it was %s" % (case.mode, begun.get("permissionMode")))
    if run.timed_out:
        return Verdict(FAILED, "stopped after %d s" % LIMIT)
    if not run.result:
        return Verdict(FAILED, "ended without a result: %s" % run.stderr[:200])
    return case.judge(run)


# --- all runs ----------------------------------------------------------------------------------------------

def run_all(chosen, times, one):
    """[(case, verdicts)]. After a usage limit, a missing login or a missing model nothing more is started."""
    rows = [(case, []) for case in chosen]
    stopped = None
    for _ in range(times):
        for case, verdicts in rows:
            got = stopped or one(case)
            verdicts.append(got)
            if got.outcome == NOT_RUN and got.note.startswith(NO_MORE):
                stopped = got
    return rows


def _keep(out, raw, case):
    name = "%s-%s" % (re.sub(r"[^a-z]+", "-", case.name.lower()), case.mode)
    Path(raw).mkdir(parents=True, exist_ok=True)
    shutil.copyfile(out, Path(raw) / ("%s-%d.jsonl" % (name, len(list(Path(raw).glob(name + "-*"))) + 1)))


def once(case, claude, model, raw, about):
    """Make the project of a case, start Claude Code in it, judge, and delete the project."""
    folder = Path(tempfile.mkdtemp(prefix=PREFIX))
    env = clean_env(os.environ)
    begin = time.monotonic()
    try:
        game = make_game(case, folder, env)
        before = cases.files_of(game)
        out = folder / "out.jsonl"
        events, stderr, timed_out = start(command_of(case, claude, model), case.prompts, game, env, out)
        got = verdict(case, Run(game, events, before, cases.files_of(game), stderr, timed_out))
        for e in events:
            if e.get("subtype") == "init":
                about.update(claude=e.get("claude_code_version"), model=e.get("model"))
        if raw:
            _keep(out, raw, case)
    finally:
        delete(folder)
    print("%-8s %4.0f s  %s (%s)  %s" % (got.outcome, time.monotonic() - begin, case.name, case.mode, got.note),
          file=sys.stderr, flush=True)
    return got


# --- the table ---------------------------------------------------------------------------------------------

def _cell(text):
    return " ".join(text.replace("|", "/").split())


def table(rows):
    lines = ["| Case | Mode | Passed | Not run | Notes |", "|---|---|---|---|---|"]
    for case, verdicts in rows:
        count = Counter(v.outcome for v in verdicts)
        notes = Counter("%s: %s" % (v.outcome, _cell(v.note)) for v in verdicts if v.outcome != PASSED)
        shown = "; ".join(note + (" (%dx)" % n if n > 1 else "") for note, n in notes.items())
        lines.append("| %s | %s | %d of %d | %d | %s |" % (case.name, case.mode, count[PASSED], len(verdicts),
                                                         count[NOT_RUN], shown))
    return "\n".join(lines)


def report(rows, head):
    release = [r for r in rows if not r[0].extra]
    extra = [r for r in rows if r[0].extra]
    parts = [head] + [table(release)] * bool(release)
    if extra:
        parts += ["Extra, no condition of a release:", table(extra)]
    return "\n\n".join(parts)


def exit_code(rows):
    """By the cases of a release; by the extra ones if only those were run."""
    counted = [r for r in rows if not r[0].extra] or rows
    outcomes = {v.outcome for _, verdicts in counted for v in verdicts}
    if FAILED in outcomes:
        return 1
    return 2 if NOT_RUN in outcomes or not outcomes else 0


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Repeat runs of the plugin with Claude Code.")
    parser.add_argument("--model", required=True)
    parser.add_argument("--times", type=int, default=10)
    parser.add_argument("--case", action="append", help="name of a case; may be given several times")
    parser.add_argument("--mode", choices=cases.MODES, help="only the rows of this mode")
    parser.add_argument("--claude", help="the program; else CLAUDE_EXE, the path, or the VS Code extension")
    parser.add_argument("--raw", help="folder to keep the raw output in")
    args = parser.parse_args(argv)
    names = sorted({c.name for c in cases.CASES})
    unknown = [n for n in args.case or [] if n not in names]
    if unknown:
        parser.error("unknown case: %s. Known: %s" % (", ".join(unknown), "; ".join(names)))
    chosen = [c for c in cases.CASES if (not args.case or c.name in args.case) and args.mode in (None, c.mode)]
    claude = find_claude(args.claude, os.environ, Path.home())
    if not claude:
        parser.error("Claude Code was not found. Name it with --claude")
    if not chosen:
        parser.error("no case has this mode")
    about = {}
    rows = run_all(chosen, args.times, lambda case: once(case, claude, args.model, args.raw, about))
    head = "guided-learning %s %s, Claude Code %s, model %s (%s), %s, %s" % (
        version.VERSION, version.plugin_hash(), about.get("claude", "?"), args.model, about.get("model", "?"),
        platform.system(), date.today().isoformat())
    print(report(rows, head))
    return exit_code(rows)


if __name__ == "__main__":
    sys.exit(main())
