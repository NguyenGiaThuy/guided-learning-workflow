# Changelog

## 0.2.0 (unreleased)

- `/setup-learning` asks for the field of the project (`domain`), two words for the texts (`words`) and whether phases have tuning (`tuning`). Every fixed text uses the project's words.
- With `"tuning": false` a phase needs no targets and goes from the build straight to the wrap-up.

## 0.1.0 (unreleased)

First version.

- Six commands: `/setup-learning`, `/start-phase`, `/approve-phase`, `/build-phase`, `/summarize-phase`, `/finish-phase`.
- Hooks that check the commands, show the status line, refuse edits of locked files, notice changes by another route, and ask for the closing text.
- A phase that is open on another branch is named there, and its scripts stay locked.
- Records and test results through one script (NUnit 3, JUnit XML, or lines of `name,pass` and `name,fail`), and a scorecard per phase.
- Rehearsal on a fake game, with a checklist and reports.
- Unit tests and a runner for repeat runs with Claude Code.
