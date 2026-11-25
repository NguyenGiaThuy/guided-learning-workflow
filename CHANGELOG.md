# Changelog

## 0.1.0 (unreleased)

First version.

- Six commands: `/setup-learning`, `/start-phase`, `/approve-phase`, `/build-phase`, `/summarize-phase`, `/finish-phase`.
- Hooks that check the commands, show the status line, refuse edits of locked files, notice changes by another route, and ask for the closing text.
- Records and test results through one script (NUnit 3, JUnit XML, or lines of `name,pass` and `name,fail`), and a scorecard per phase.
- Rehearsal on a fake game, with a checklist and reports.
- Unit tests and a runner for repeat runs with Claude Code.
