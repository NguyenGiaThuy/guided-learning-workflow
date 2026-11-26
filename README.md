# Guided learning

A Claude Code plugin for people who build a game with an AI in order to learn how games are made.

You build the game in phases. In each phase the AI does the surrounding work, and you write the key scripts and do the tuning. Every phase ends with a concept summary in which your own answers come first, with lessons, and with a scorecard of what you learned. It is not a grade.

The plugin does not rely on the AI following written rules. A script keeps the state in files of your game, and hooks check your commands and refuse edits. So it works the same way every time, and no step depends on one chat.

Version 0.1.0 is not released yet. See [CHANGELOG.md](CHANGELOG.md) and [the design](docs/design.md).

## Commands

You type them. The AI cannot start them. Every status, blocked command and closing text ends with the next command, so you need not remember them.

| Command | Hint | Description |
|---|---|---|
| `/setup-learning` | | Step 0, once per game: set up guided learning in this project. |
| `/start-phase` | `<N> [skip: reason]` | Step 1: begin PLANNING phase N with the AI. Checks that the phase before it is finished. Writes no code. |
| `/approve-phase` | `<N> [change: reason]` | Step 2: you ACCEPT the plan of phase N and lock its targets. Writes no code. |
| `/build-phase` | `[N]` | Step 3: the AI WRITES the boilerplate (TODO shells, tests, the rest), or resumes it. |
| `/summarize-phase` | `[N]` | Step 4: YOUR TURN. Shows your progress and resumes your coding, tuning and wrap-up. |
| `/finish-phase` | `<N>` | Step 5: CLOSE phase N. Checks that everything is done. |

## Installation

You need Claude Code, Python 3.9 or newer as `python` or `python3`, and `bash` (on Windows: Git Bash). The plugin needs no other packages. Git is optional, but the branch of a phase is only checked with it.

In Claude Code type:

```text
/plugin marketplace add <owner>/guided-learning-workflow
/plugin install guided-learning@guided-learning-workflow
```

`<owner>` is the account that holds the repository. Nothing is published yet. Until then, start Claude Code with a copy of this repository: `claude --plugin-dir <folder of this repository>`.

Open a new chat. In a project without guided learning the hooks do nothing, so you can install the plugin for all your projects.

## The first phase

1. Open your game in Claude Code and type `/setup-learning`. The AI asks for the settings of your game: folders, file extensions, test suites, your background. Then open a new chat. In the terminal it begins with the status line `Learning hooks: on (0.1.0 ...)`. The VS Code panel does not show that line, so `/summarize-phase` and `/build-phase` begin with it too. If you do not see it, or it says `not running`, the hooks do not run. See "What is not guaranteed".
2. Type `/start-phase 1`. You plan with the AI: the concepts you want to learn, 3 to 5 scripts you will write yourself, balance targets with numbers, and questions for the end. No code is written. Check out the branch of the phase before the next step.
3. Read the plan (`phase-1.plan.json`), without the points of the questions. Type `/approve-phase 1`. The plan is locked. Later you can change it only by hand, with `/approve-phase 1 change: <reason>`.
4. Type `/build-phase 1`. The AI writes the rest of the game, your scripts as shells with `TODO(owner 1.1)` comments, and tests for them that fail. At the end it hands over, and your scripts are locked against its edits. A phase may have several parts, each with its own build.
5. Open a new chat and type `/summarize-phase 1`. You see what is done and what is next. Write your code in the editor. Ask for help when you want it, in four levels: a question, a pointer, more pseudo code, the solution in the chat. Remove the owner mark of a test when it passes. Close the chat whenever you like: the same command goes on from there.
6. When your scripts are done, `/summarize-phase 1` goes on with the tuning. You change the numbers and say before each run what you expect. Then comes the wrap-up: you answer the questions in your own words, the AI names what is missing, and you write the lessons.
7. Type `/finish-phase 1`. It lists what is open, or closes the phase and shows the closing text. Closing changes the two phase files (`phase-1.json` and `phase-1.md`), so commit them now. Merge the branch, open a new chat and type `/start-phase 2`.

## Rehearsal

You can try the whole workflow on a fake game, Lantern Keeper, before you use it for yours.

- Set `{"rehearsal": true}` in `.claude/learning/config.json` of your game and save. At the next prompt the commands work on a fake project in `.claude/learning/rehearsal/`. They do not touch your real game, and the status line says `REHEARSAL run 1` (in the VS Code panel: the first line of `/summarize-phase`).
- Go through [the checklist](rehearsal/checklist.md). A copy of it is in the fake project. The script ticks what it sees, you tick the rest. Branches, merges and test results are simulated.
- A report of each run is kept in `.claude/learning/rehearsal-reports/`, and `/summarize-phase` shows how this run differs from the last one.
- Save the file again to start over. Set it to `false` to go back to your game.

## What is not guaranteed

- **What stays a judgement of the AI:** how good a hint, a review or an explanation is, and that it saves your words unchanged. Planned questions with planned points narrow this as far as possible.
- **Changes through the shell are noticed, not prevented.** The hooks refuse the edit tools. A shell command, a program or an MCP server can still change a locked file. Then you are told, and the AI is told to ask you before it does anything else. Nothing is undone. An AI that is set on it could also call the script of the plugin in ways that no hook sees.
- **The hooks need Python and bash.** If they cannot start, Claude Code goes on without them. You notice it because the status line is missing, and `/summarize-phase` fails with a message or begins with `Learning hooks: not running in this chat`.
- **The VS Code panel** does not show the messages of the hook that starts a chat. The status line is then only in `/summarize-phase` and `/build-phase`.
- **Not tried:** changes through an engine's MCP server, and bypass mode (`--dangerously-skip-permissions`).
- **Permission questions.** Claude Code lets a command run the script without asking only in the answer to that command. When you go on talking in the same chat, it asks for your permission in the default mode before the AI writes a record. It also asks for the git commits in `/build-phase`.
- The points of the wrap-up questions are in the plan file, and you can read them. Do not.

## Platforms

Tested: Windows 11 with Git Bash, Python 3.14 and Claude Code 2.1.332, in print mode (`claude -p`), with Sonnet, each enforced behavior 5 times ([table](docs/repeat-runs/0.1.0.md)). macOS, Linux and other versions were not tried. Above all on macOS: whether an edit of a locked file is refused when its path is written in another mix of upper and lower case.

Test results are read from NUnit 3 XML (Unity writes it), JUnit XML, or lines of `name,pass` and `name,fail`. So far only sample files were read, none of a real engine. Other AI tools than Claude Code do not work.

## Contributing

- Unit tests, with the standard library only: `python -m unittest discover -s tests -v`. After a change of the manifests or skills: `claude plugin validate .`.
- Repeat runs: `python tests/repeat/run.py --model <model> --times 10` starts Claude Code in throwaway projects and judges each run by files and output, not by asking a model. **It uses your Claude account**: the release run with `--times 10` is about 220 starts, and 30 more with the extra rows. `--jobs 4` lets up to four runs be active at once (1 to 8, else one), `--case`, `--mode` and `--no-extra` choose rows, and `--raw <folder>` keeps the output. Your own settings, plugins and MCP servers are not loaded. A row counts only with 10 of 10. *Not run* (no connection, a usage limit, or the AI did not try) is no pass. The throwaway projects are deleted, but Claude Code itself keeps small folders named `...gl-repeat-...` under `~/.claude/projects` for some runs. You may delete them.
- If you enable this plugin in its own repository, the template in `rehearsal/project` counts as a project: the hooks refuse edits of its locked files by the AI.
- No person's name, email or real game in any file. Examples use Lantern Keeper.

## License

MIT, see [LICENSE](LICENSE).
