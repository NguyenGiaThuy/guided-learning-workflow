# Design: the project's field, its words, and optional tuning

Date: 2026-11-26. Status: approved by the owner in conversation; this document waits for the owner's review.

## Why

Guided learning was written for games. Its mechanics fit any codebase: phases with locked steps, `TODO(owner)` scripts that the owner writes, help in four levels, questions answered in the owner's words, and a scorecard. What does not fit other fields is the wording ("game", "balance targets") and the tuning step, because some code has nothing to measure. The owner wants to name the field at `/setup-learning`, get wording that suits it, and choose once whether the project has a tuning step.

## Goals

- `/setup-learning` asks for the field and suggests fitting words, and asks whether tuning is wanted.
- Every fixed text the owner sees uses the project's words.
- A project without tuning plans, builds and finishes phases without any target.
- A project set up before this change behaves exactly as today.

## Non-goals

- A list of fields built into the script.
- A third word, for example for the user of the project (player, customer). The owner found two words enough.
- A new fake project for the rehearsal. Lantern Keeper stays a game.
- Translations. Texts stay English.

## Anti-goals

- Wording made up by the AI at run time. Within one project the texts must stay word for word the same, because the hooks and the repeat runs compare them.
- Breaking a phase that is open when the settings change.

## Approaches

1. **A fixed list of fields**, each with its words in `texts.py`. The most predictable; a field that is not in the list gets generic words.
2. **Words stored in `project.json`** (chosen by the owner). The AI suggests the words at setup, the owner confirms them, and from then on the script uses them, so the texts of that project are fixed. It works for any field. The cost: the script checks the words, and the tests cover changing words.

## The settings

Three new optional keys in `.claude/learning/project.json`:

| Key | Value | Default when missing | Used by |
|---|---|---|---|
| `domain` | the field in the owner's words, one line, at most 100 characters, for example `web backend in Go` | none | the AI only: hints, examples, plan questions |
| `words` | `{"project": "...", "targets": "..."}` | `{"project": "game", "targets": "balance"}` | the fixed texts |
| `tuning` | `true` or `false` | `true` | plan check, status, scorecard, skills |

- `words.project` is what the thing is called: `game`, `app`, `model`, `service`. `words.targets` is the word placed before "target" or "targets": `balance`, `performance`, `quality`. A word before "target" means the script never forms plurals of the owner's words.
- Each word: one or two words of letters, digits or hyphens, one line, 1 to 20 characters. Texts that start a sentence with it capitalize its first letter ("Balance: 2/3 targets met").
- `words` may name only one of the two; the other keeps its default.
- A wrong type or a word that fails the check is an error like any other wrong value of `project.json` today (hooks refuse, the message names `project.json` and the problem). `setup` refuses such input as it refuses other wrong settings. The three keys are known keys, so they are not reported as unknown.

## `/setup-learning`

The skill asks for the three settings together with the existing ones, in the same single message, each with a suggestion and its reason:

- `domain`: suggested from what the folder shows (engine, framework, package files), or asked in a new folder.
- `words`: suggested from the domain. For a game: `game`, `balance`.
- `tuning`: suggested `true` if the field has numbers worth tuning (games, performance, accuracy), else `false`, with one sentence on what the tuning step is.

The engine question is asked only for a game. The existing rule stays: nothing is written before the owner answers. A project set up before keeps working; running `/setup-learning` there again adds nothing on its own, and the owner may add the keys by hand.

## The fixed texts

Every owner-facing text in `texts.py` that says "game" or "balance" takes the project's words. Today these are, among others: the description of `/setup-learning` as shown by the script, the gap "No balance target.", the plan-gap explanation of targets, the scorecard line "Balance: x/y targets met.", the setup messages about folders "of the game", "This game was set up before", "This folder is inside the game at ...", and the rehearsal lines "not your game" and "leave the real game alone". The builder finds the complete list by search; any text a hook or judge compares must come from one function with the words as input.

In a rehearsal the fake project's own `project.json` holds its words (game, balance), and the lines about the real project use the real project's words.

The descriptions in the skills' frontmatter cannot vary by project. They become neutral: "Step 0, once per project: ...".

## Tuning off

With `tuning: false`:

- **Plan check:** a phase needs no target. "No ... target" is no gap. A target that is there is checked as today.
- **`/start-phase`:** the skill does not propose targets.
- **Status:** the line "Then: tune (...), wrap-up" leaves out the tune part when the phase has no target.
- **State:** unchanged. A phase whose scripts are done and which has no open target goes to the wrap-up already today.
- **Scorecard:** the balance line and the predict line are left out when the phase has no target and no tuning round was recorded.
- **Skills:** `/summarize-phase` skips the tuning section when there is no target.

Targets in a plan always work as today, also with `tuning: false`. So switching the setting during an open phase changes nothing for that phase, except whether a missing target is a gap in a plan that is not approved yet.

## Wording in the AI's instructions

Skills, templates and the CLAUDE.md section say "project" where they say "game" today, and tell the AI to read `domain` and `words` from `project.json` and to use them when it talks to the owner. The README explains the three settings and the tuning switch; `docs/design.md` gets the settings table and the tuning rule.

## Testing

- Unit tests (standard library only): defaults when keys are missing; checks of each key, including wrong types and words that are too long or have a line break; each changed text with default and with other words; the plan check, status and scorecard with tuning off, with and without targets; a phase played through with tuning off in `tests/test_whole_phase.py`; setup with the new keys.
- Repeat runs: all release cases, 3 times each, with Sonnet (the owner's choice), because the texts change everywhere. New cases: a blocked command in a project with other words (the refusal names them), and finishing a phase with tuning off and no target. The table goes into `docs/repeat-runs/`.
- The owner rehearses once in the VS Code panel.

## Left to the builder

- How the words reach the text functions (a parameter, or a small object passed along). Every text compared by a hook or judge must have a single source.
- The exact sentences of the setup skill, within the rules above.
- The version and the branch. My call: version 0.2.0 with a CHANGELOG entry, built on a branch `build-0.2.0` from `main`, never pushed without the owner's word.
