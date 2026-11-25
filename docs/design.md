# Guided learning workflow: design

**Status:** approved by the owner on 2026-11-25.

Items marked **✓** were chosen by the owner of this repository. Everything else is a proposal. "Owner" below means the person who learns: the owner of the game.

## Intent

- ✓ A workflow for people who build a game with an AI in order to learn how games are made. The AI does the surrounding work, the owner writes the key scripts and does the tuning, and every phase ends with a concept summary, lessons learned and a measure of what was learned.
- ✓ Reusable for any game project, as a Claude Code plugin. ✓ MIT license.
- ✓ It behaves the same way every time and does not rest on an AI following written rules.

**Goals:** the owner writes real game code; learning is measured the same way every phase; what a script can decide, a script decides; one update reaches every game.

**Non-goals:** other AI tools than Claude Code, grading, teaching a programming language, running game engines (it only reads their test results).

**Anti-goals:** an agent fills in the owner's code; balance targets invented after seeing the result; a wrap-up that repeats what the AI wrote; state that exists only in a chat.

## Approaches

1. ✓ **A Claude Code plugin.** Install once per project, update from one place, pin a version. Works only in Claude Code.
2. Template files copied into each game. Simple and editable, but fixes do not reach the copies.
3. A git submodule. One source, but hooks are wired by hand in each game, and submodules are easy to get wrong.

For the rules themselves: written rules only, commands only, or a script with hooks. ✓ The last, because the owner asked for consistent behavior.

## The four steps of a phase

A phase is whatever the game calls a stage or milestone.

### 1. Plan
Before any code of the phase, the plan file gets, and the owner approves:
- **Concepts** the phase teaches.
- **Owner scripts:** ✓ the core script of each concept, 3 to 5 in all. For each: path, concept, TODO numbers, names of its tests.
- **Balance targets:** ✓ each with a number or range, how it is measured, and the settings that influence it.
- **Wrap-up questions,** at least one per concept, with the points an answer must contain.

### 2. Build
- ✓ The AI writes each owner script as a shell: fields, signatures, and `// TODO(owner S.T)` (script S, step T) with pseudo code and hints. It compiles and does nothing harmful. The comment style follows the language.
- A TODO says what must be true, not each line. Hints explain the engine and game ideas, at the level of the owner's experience (`project.json`).
- The AI writes the tests first. They carry a mark that normal runs skip (in NUnit `[Explicit("Owner")]`), and the owner removes it when the test passes.
- ✓ The owner writes the code. ✓ The AI reviews: it names the problem or asks a question, and does not rewrite.
- Help has four levels, on request: 1 a question, 2 a pointer to the concept or API, 3 more pseudo code, 4 the solution in the chat, which the owner types in.

### 3. Tune
- ✓ The owner changes numbers. ✓ The AI says which setting influences which target, never the value.
- Each tweak is logged: change, predicted direction, result, right or wrong. At most 6 rounds.
- A target still missed needs a written reason. A target changes only through `/approve-phase N change: <reason>`.

### 4. Wrap up
In this order, so that the owner's answers come first:
1. The AI asks the planned questions. The owner answers in their own words, saved one by one.
2. The AI names the points that are missing, and asks again.
3. The AI rates each concept by the points: *on my own* (all without a hint), *with help* (all after hints), *can't yet*.
4. The AI writes the **concept summary**: the idea and its usual name, how this game does it, what it resembles in the owner's background, the alternative not chosen, something that went wrong here.
5. The owner gives 3 to 5 **lessons**, at least one about the process and one thing to do differently.
6. The script fills in the scorecard.

| Scorecard | Measure |
|---|---|
| Build | Owner scripts passing their tests, and the highest help level of each |
| Predict | Tweaks with the right predicted direction, out of all |
| Balance | Targets met, out of those planned |
| Explain | The rating of each concept |
| Process | What surprised me, what I would do differently |

It shows the trend between phases. It is not a grade.

## Commands

All are typed by the owner and are `disable-model-invocation`, so the AI cannot start them.

| Command | What it does |
|---|---|
| `/setup-learning` | Asks for the settings of the game, writes `project.json` and the other files below |
| `/start-phase N` | Checks that phase N-1 is done or skipped. Blocks otherwise and lists what is open. `/start-phase N skip: <reason>` records the skip and carries open items over. Then planning starts. Phase 1 has no check. |
| `/approve-phase N` | Checks that the plan is complete, and locks it. Status becomes `build`. Nothing is built yet. |
| `/build-phase [N]` | The AI starts or resumes its work: shells, tests, and everything else that is not the owner's. Blocked before approval, and while it is the owner's turn. |
| ✓ `/summarize-phase [N]` | Shows where phase N stands (default: the latest) and goes on with the first open step |
| `/finish-phase N` | Checks everything. Blocks and lists what is open, or writes `done`. Typing it is the owner's agreement to the scorecard. |

### Descriptions ✓

Every command has a description and an argument hint, shown in the `/` menu. They start with the place in the sequence and say who acts:

| Command | Hint | Description |
|---|---|---|
| `/setup-learning` | | Step 0, once per game: set up guided learning in this project. |
| `/start-phase` | `<N> [skip: reason]` | Step 1: begin PLANNING phase N with the AI. Checks that the phase before it is finished. Writes no code. |
| `/approve-phase` | `<N> [change: reason]` | Step 2: you ACCEPT the plan of phase N and lock its targets. Writes no code. |
| `/build-phase` | `[N]` | Step 3: the AI WRITES the boilerplate (TODO shells, tests, the rest), or resumes it. |
| `/summarize-phase` | `[N]` | Step 4: YOUR TURN. Shows your progress and resumes your coding, tuning and wrap-up. |
| `/finish-phase` | `<N>` | Step 5: CLOSE phase N. Checks that everything is done. |

Every status, blocked command and closing text ends with the next command and its description, so the names need not be remembered: `Next: /summarize-phase 2  (step 4: your turn)`. The README shows the same table. The texts live in one place in the script, and a test compares them with the skill files.

### `/build-phase` starts the AI's work

A phase has one or more **parts**, listed in the plan file. Each part is AI work followed by the owner scripts it prepares; the last part may have no owner scripts. With Superpowers, a part is one plan document.

1. The hook checks whose turn it is. Not approved: blocked, with what is missing. The owner's turn: blocked, with the open TODOs and tests. Otherwise the script names the part, and which of its tasks are done.
2. The AI does the tasks of that part: the shells of the owner scripts, their failing tests, and the rest. With Superpowers it uses the execution method chosen at planning.
3. At the end the AI runs `learning.py hand-over`. The script checks that every planned TODO is in its file, that every planned owner test is in the test code, that the project's suites were recorded after the last code change and pass, and that the owner tests were run and fail. If so, it **locks the owner scripts of this part** and it is the owner's turn. If not, it lists what is missing. A shell that does not pass is not handed over.
4. When the owner scripts of the part pass their tests, it is the AI's turn again, if a part is left.

It prints at the end:

```
Phase 2, part 1 handed over. Your turn: 3 scripts, 8 TODOs.
Next: open a new chat and type /summarize-phase 2
```

Run again after a closed chat, it goes on with the part's next open task.

### `/summarize-phase` resumes anywhere ✓

The script works out the state from the project each time, and its output is inserted before the AI sees the skill:

| Question | Read from |
|---|---|
| Right branch? | The branch in the phase file. If another is checked out, it says so and stops. |
| TODOs left? | `TODO(owner S.T)` in the owner scripts, including work not committed, compared with the plan |
| Finished TODOs right? | The recorded results of that script's tests. TODOs gone with a failing test: *in progress*. Results older than the code: *unknown*, and it offers to run them. |
| Targets, wrap-up? | The phase files |

```
Phase 2 - build          4 of 8 TODOs done
  Owner 1 Charger        done    tests 5/5   help: 1
  Owner 2 Shooter        2 of 4  tests 2/6   <- next: TODO 2.3
  Owner 3 Orbit blades   not started
Then: tune (0 of 5 targets), wrap-up
```

- Order: build, tune, wrap-up. A step that is complete asks for a new chat for the next one.
- Everything is saved as soon as it happens, so a chat can be closed at any time.
- While it is the AI's turn it says so and names `/build-phase`. It never builds.
- Owner scripts stay locked against AI edits from the hand-over until the phase is done.
- On a done phase it shows the summary, lessons and scorecard, and offers to go over any concept again.

### What `/finish-phase` checks

- No `TODO(owner)` and no owner mark of this phase is left. Every suite named in `project.json` has recorded results that are newer than the last code change and all pass.
- Every target has a measured value that meets it, or a written reason.
- Every concept has an answer, and a rating of at least *with help*.
- The concept summary has an entry for each concept. There are 3 to 5 lessons. Both process sentences are there.

Then it prints once, and starts nothing:

```
Phase 2 is done. Saved in Docs/learning/phase-2.md.
Branch stage-2: not merged.
Carried to phase 3: <weak concepts> | <what you would do differently>
Next: commit, merge the branch, then open a new chat and type /start-phase 3
```

## Consistent behavior ✓

| Behavior | Mechanism |
|---|---|
| A new chat knows the state | `SessionStart` hook prints one status line |
| Commands are checked before the AI sees them | `UserPromptSubmit` hook: blocks, or does the writing itself |
| Owner code is not changed by AI | `PreToolUse` hook refuses Edit, Write and NotebookEdit on locked owner scripts, and any edit that removes a `TODO(owner)`. Before `/approve-phase` it refuses all edits in the code folders, so no code comes before the plan. After that and before `/build-phase` too. Also in subagents. |
| Changes by another route are noticed | `PostToolUse` hook compares owner scripts and workflow files before and after a tool call, tells the owner, and stops the agent |
| The closing text appears | `Stop` hook holds the answer until it contains the text; once per phase, at most 3 tries, then the script shows it to the owner itself |
| Records have one form | The AI records help levels, tweaks, measurements and ratings only through `learning.py log`, which validates them. Edits of the JSON files are refused. |

- The hooks also guard `config.json`, `project.json` and the plan. The owner edits those by hand.
- A hook that fails inside refuses the action and says why. If Python cannot start, Claude Code goes on without hooks. Then the status line is missing, and the `!` command of `/summarize-phase` fails with a message.
- In a project without `project.json` every hook does nothing, so the plugin can be installed for all projects.
- Hooks run in the owner's working copy, so a change by the owner in an editor is never refused.

**What stays a judgement:** how good a hint, a review or an explanation is. The planned questions and points narrow it as far as possible. Saving the owner's words unchanged is also up to the AI. The points are in the plan file; the owner should not read them before the wrap-up.

## Files

In the plugin:

```
.claude-plugin/plugin.json, marketplace.json    this repository is plugin and marketplace
hooks/hooks.json
scripts/learning.py                             Python 3.9+, standard library only
scripts/run.sh                                  finds python or python3
skills/<one folder per command>/SKILL.md
templates/                                      phase file, README, CLAUDE.md section, .gitignore lines
rehearsal/                                      template of the fake phases, checklist
tests/                                          unit tests and the repeat runner
README.md, LICENSE, CHANGELOG.md, docs/design.md
```

In a game, written by `/setup-learning`:

| File | Content | In git |
|---|---|---|
| `.claude/learning/project.json` | code folders, file extensions, TODO and test marks, suites and their result format, folder for phase files, the owner's background | yes |
| `.claude/learning/config.json` | `{ "rehearsal": false }` | no |
| `.claude/learning/local/`, `rehearsal/`, `rehearsal-reports/` | state of this machine, rehearsal | no |
| `<docs>/learning/phase-N.plan.json` | concepts, owner scripts, targets, questions and points. Locked after approval, with its hash | yes |
| `<docs>/learning/phase-N.json` | status, branch, locks, log, ratings, test results. Written only by the script | yes |
| `<docs>/learning/phase-N.md` | notes for later, answers, concept summary, lessons. Prose, written by AI and owner | yes |
| `CLAUDE.md` | a short section, added after the owner agrees | yes |

Test results: `learning.py record-tests <suite> <file>` reads NUnit 3 or JUnit XML. Only Unity is tested. An engine with no such output can use a file of `name,pass|fail` lines.

## Sessions ✓

The learning conversations are kept apart from the development chat. Plan; build, one per plan; help, one per owner script; tune; wrap-up: each has its own chat. Nothing that a later step needs may exist only in a chat. Before a session ends, the AI adds decisions, surprises and what went wrong to *Notes for later*. Help and wrap-up sessions read the phase files, the code and the git history, not other chats.

## With Superpowers

Optional. If it is installed, its skills stay as they are, and the `CLAUDE.md` section settles these points, since the owner's instructions come before the skills:

| Skill | Rule |
|---|---|
| `writing-plans` | Owner work goes under `### Owner N`. Agents are only given `### Task N`. Planning ends with `/approve-phase`, and building starts with `/build-phase`. Choosing an execution method does not start it. |
| `subagent-driven-development`, `executing-plans` | A plan is one part and ends with the hand-over. The next plan starts with the next `/build-phase`, so no plan has to pause. |
| `test-driven-development`, `verification-before-completion` | Owner tests are outside normal runs. For the shell, the expected result is that they compile and fail. |
| reviews | `TODO(owner)` is intended. Reviewers check the shell, the tests and the hints. |
| `systematic-debugging` | For owner code: find the cause, then help at the level asked for. |
| `using-git-worktrees` | A branch in the project folder, so the owner can write in the open editor. |
| `finishing-a-development-branch` | The wrap-up and `/finish-phase` come first. |

## Rehearsal ✓

`.claude/learning/config.json` holds a switch, `{ "rehearsal": true }`. While it is on, the commands work on a fake project in `.claude/learning/rehearsal/`. ✓ Every change from off to on starts the rehearsal again, so the workflow can be tested for consistency whenever it changes.

| | Off | On |
|---|---|---|
| Commands read and write | the real phase files and code | `rehearsal/` only |
| `/start-phase` | starts planning | stops at "planning would start here" |
| Branch, merge, test results | real | simulated |
| Protection of real owner code and files | on | on |
| Status line | `Learning hooks: on (0.1.0 a1b2c3)` | `Learning hooks: on (REHEARSAL run 4, 0.1.0 a1b2c3)` |

- **Restart:** whenever the switch is on and `config.json` was saved since the script last looked. So off to on always restarts, even with no chat in between, and saving again while on does too. It takes effect at the next prompt or new chat.
- A missing or broken file means off, and the status line says so. The AI may not edit it.
- **The fake project** has a finished phase 1 and a half-finished phase 2: two small files, five TODOs, three targets, two concepts. `learning.py rehearse pass|fail|merge|branch` simulates test results, the merge and a wrong branch.
- **The checklist** says what to type and expect: resuming at 50%; resuming after closing the chat in the middle; a TODO removed with a failing test; asking the AI to write a TODO; `/finish-phase` too early; finishing; `/start-phase` too early, with a skip, and in a new chat; `/build-phase` before approval, resumed in the middle, and on the owner's turn; a hand-over with a missing TODO; an edit of code before approval; the wrong branch. The script ticks what it sees, and the owner ticks the rest.
- **Reports** are kept per run. `/summarize-phase` shows how this run differs from the last one. The code after the version is a hash of the plugin's files.

## Testing before release

| Step | Who | Passes when |
|---|---|---|
| 1. Unit tests of `learning.py`: every state of a phase, broken and missing files, the switch | AI | All pass |
| 2. Repeat runs: each enforced behavior 10 times, with the plugin loaded by `--plugin-dir`, in default, acceptEdits and auto mode, with the model used for real work | AI | 10 of 10. A miss is a defect; after the fix the 10 start again |
| 3. Rehearsal in the VS Code panel, twice, the second time in new chats only | Owner | Every line of the checklist matches |
| 4. A first real game: AI edits through the engine's MCP, real result files from editor and batch mode | AI | Noticed and read correctly |
| 5. Release 0.1.0: push | Owner says so | |
| 6. Pilot: one real phase | Owner | The owner agrees to keep it |

Before every later release, steps 1 to 3 are repeated. Releases are git tags with a version in `plugin.json`, so a game can stay on one.

**Already tried** on 2026-11-25, in throwaway projects with Claude Code 2.1.331 in print mode on Windows, with a small model and mostly once: the status text at session start, the inserted status (same line in 5 of 5 runs), blocking `/start-phase`, refusing edits in acceptEdits and auto mode and in a subagent, noticing a change through the shell, refusing an AI that starts `/finish-phase`, and sending back an answer without the closing text. As a plugin: the status, blocking, refusal, and the short command name. `!` commands need `allowed-tools`.

**Not tried:** the VS Code panel, changes through an engine's MCP, bypass mode, macOS and Linux.

## Publishing

- The repository is public. It holds nothing about a person or a particular game: examples and the rehearsal use invented ones.
- Commits use the GitHub hidden email address, set for this repository only.
- Nothing is pushed before step 5.

## Left to the builder

Command wording, JSON field names, the fake game, names of tests, and the layout of the reports.
