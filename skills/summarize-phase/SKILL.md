---
name: summarize-phase
description: "Step 4: YOUR TURN. Shows your progress and resumes your coding, tuning and wrap-up."
argument-hint: "[N]"
disable-model-invocation: true
allowed-tools: Bash(bash *run.sh* status*), Bash(bash *run.sh* log *), Bash(bash *run.sh* record-tests *)
---

The status of the phase, worked out from the project:

!`bash "${CLAUDE_PLUGIN_ROOT}/scripts/run.sh" status $ARGUMENTS`

Show it first, unchanged. Do not work it out again. Then do what fits it, and only that. End every answer with the next step.

- **Not set up**: say that `/setup-learning` comes first, and stop. **No phase**: name the command it names, and stop.
- **Wrong branch**: say so, with the command to switch, and stop.
- **Planning or skipped**: name the next command and stop.
- **The AI's turn**: name `/build-phase N` and stop. Never build here.
- **Done**: offer to go over any concept again.
- **Otherwise**: go on with the first open step: build, tune, wrap-up. When a step is complete, stop: ask the owner to open a new chat and type `/summarize-phase N` for the next one.

Read `phase-N.plan.json` and *Notes for later* in `phase-N.md` first. Both are in the folder `docs` of `.claude/learning/project.json`. Save everything as soon as it happens: the chat may be closed at any time. Do not edit `phase-N.json` or the plan. Before the chat ends, add decisions, surprises and what went wrong to *Notes for later*.

Records go through `bash "${CLAUDE_PLUGIN_ROOT}/scripts/run.sh"`, followed by the calls below. Add `phase=N` to each.

## Build: the owner writes the code

- Name the next TODO and explain what must be true. Then wait. Owner scripts are locked: never edit them, also not by a shell command.
- Help only on request, and start at the lowest level that can help: 1 a question, 2 a pointer to the concept or API, 3 more pseudo code, 4 the solution in the chat, which the owner types in. Say the level. Record it: `log help script=<id> level=<1-4>`
- Review on request: name the problem or ask a question. Do not rewrite.
- Results are old or missing: offer to run the tests of the script, with the owner mark. Record the file: `record-tests <suite> <file>`
- When a test passes, the owner removes its owner mark.

## Tune: the owner changes the numbers

- Say which setting influences which target. Never say or change a value.
- For each tweak ask for the predicted direction before the run. Then: `log tweak change="<what>" predicted=<up|down|none> target=<id> before=<number> after=<number>`
- Record what was measured: `log measure target=<id> value=<number>`
- At most 6 rounds. For a target that is still missed the owner gives a reason: `log reason target=<id> text="<the owner's words>"`
- A target changes only through the owner: edit the plan by hand, then `/approve-phase N change: <reason>`.

## Wrap-up: in this order

The owner's answers come first, so say nothing about a concept before them.

1. Ask the planned questions, one by one. Save each answer at once under `### <question id>` in *Answers*, in the owner's words, unchanged. Do not correct them. Do not show the points.
2. Name which points are missing, without giving the answer, and ask again. Add the new answer below the first one.
3. Rate each concept by the points: `on my own` (all without a hint), `with help` (all after hints), `can't yet`. Record it: `log rating concept=<id> rating="<rating>"`. A concept at `can't yet` is gone over and asked again.
4. Write the *Concept summary*, one `### <concept name>` for each: the idea and its usual name, how this game does it, what it resembles in the owner's background, the alternative not chosen, something that went wrong here.
5. Ask for 3 to 5 *Lessons*, at least one about the process and one thing to do differently. Save them as list items in the owner's words. Ask for the two sentences of *Process*: `Surprised me:` and `Differently:`.
6. Run `bash "${CLAUDE_PLUGIN_ROOT}/scripts/run.sh" status N`. It shows the scorecard, or what is still open. Show it. If nothing is open, ask the owner to type `/finish-phase N`.
