# Guided learning

This folder holds the records of guided learning. You build the game in phases: the AI does the surrounding work, you write the key scripts and do the tuning. Each phase ends with a concept summary, lessons and a scorecard.

## Commands

You type them in Claude Code. Every status ends with the next one, so you need not remember them.

| Command | Hint | Description |
|---|---|---|
| `/setup-learning` | | Step 0, once per project: set up guided learning in this project. |
| `/start-phase` | `<N> [skip: reason]` | Step 1: begin PLANNING phase N with the AI. Checks that the phase before it is finished. Writes no code. |
| `/approve-phase` | `<N> [change: reason]` | Step 2: you ACCEPT the plan of phase N and lock its targets. Writes no code. |
| `/build-phase` | `[N]` | Step 3: the AI WRITES the boilerplate (TODO shells, tests, the rest), or resumes it. |
| `/summarize-phase` | `[N]` | Step 4: YOUR TURN. Shows your progress and resumes your coding, tuning and wrap-up. |
| `/finish-phase` | `<N>` | Step 5: CLOSE phase N. Checks that everything is done. |

## Files

| File | What it holds | Who writes it | In git |
|---|---|---|---|
| `phase-N.plan.json` | Concepts, owner scripts, targets, questions and points. Do not read the points before the wrap-up. | the AI with you while planning, then locked | yes |
| `phase-N.json` | Status, branch, locks, log, ratings, test results | only the script | yes |
| `phase-N.md` | Notes for later, answers, concept summary, lessons | you and the AI | yes |
| `.claude/learning/project.json` | Settings of this game | you, by hand | yes |
| `.claude/learning/config.json` | `{"rehearsal": false}`: the switch of the rehearsal | you, by hand | no |
| `.claude/learning/local/`, `rehearsal/`, `rehearsal-reports/` | State of this machine, rehearsal | only the script | no |

## If a file is damaged or missing

- A file in git: see what changed with `git diff -- <file>`, and bring back the last saved one with `git restore <file>`. Commit often, because the records since the last commit are lost this way.
- The plan of an approved phase: restore it, or accept your change with `/approve-phase N change: <reason>`.
- `config.json` or this README: type `/setup-learning` again. It adds what is missing and overwrites nothing.
- `local/`, `rehearsal/`: may be deleted. They are made again. The workflow then does not notice on another branch that a phase is done and not merged, or, until the next `/build-phase` or hand-over, that it is open.
