---
name: summarize-phase
description: "Step 4: YOUR TURN. Shows your progress and resumes your coding, tuning and wrap-up."
argument-hint: "[N]"
disable-model-invocation: true
allowed-tools: Bash(bash *run.sh* status*), Bash(bash *run.sh* log *), Bash(bash *run.sh* record-tests *), Bash(bash *run.sh* rehearse *)
---

The status of the phase, worked out from the project:

!`bash "${CLAUDE_PLUGIN_ROOT}/scripts/run.sh" status $ARGUMENTS session=${CLAUDE_SESSION_ID}`

Show it first, unchanged. Do not work it out again. Then do what fits it, and only that. End every answer with the next step.

- **REHEARSAL**: its rules come first: the other folder, no git, and simulated tests in place of real ones. Run `rehearse` only when the owner says so; if results are missing or old, ask the owner. Otherwise do the same as always.
- **Not set up**: say that `/setup-learning` comes first, and stop. **No phase**: name the command it names, and stop.
- **Wrong branch**: say so, with the command to switch, and stop. **Done on a branch that is not merged**: say so, name the next step, and stop.
- **Planning or skipped**: name the next command and stop.
- **The AI's turn**: name `/build-phase N` and stop. Never build here.
- **Done**: offer to go over any concept again.
- **Otherwise**: go on with the first open step: build, tune, wrap-up. One chat is for one owner script, for the tuning or for the wrap-up. When that is complete, stop: ask the owner to open a new chat and type `/summarize-phase N`.

Read the whole `phase-N.md` and `phase-N.plan.json` first. Both are in the folder `docs` of `.claude/learning/project.json`. The code and the git history tell the rest, other chats do not. Save everything as soon as it happens: the chat may be closed at any time. Do not edit `phase-N.json` or the plan. Before the chat ends, add decisions, surprises and what went wrong to *Notes for later* in `phase-N.md`. Notes go there and not into `log note`, which is shown nowhere.

Records go through `bash "${CLAUDE_PLUGIN_ROOT}/scripts/run.sh"`, followed by the calls below. Add `phase=N` to each. The owner's words never stand in the command itself: the shell would change them. Write `-` for that field and give the text as shown, with `'END'` in quotes.

## Build: the owner writes the code

- Name the next TODO and explain what must be true. Then wait. Owner scripts are locked: never edit them, also not by a shell command.
- Help only on request: 1 a question, 2 a pointer to the concept or API, 3 more pseudo code, 4 the solution in the chat, which the owner types in. A level the owner names is used as named. Otherwise start at the lowest that can help. Say the level. Record it: `log help script=<id> level=<1-4>`
- Review on request: name the problem or ask a question. Do not rewrite.
- Results are old or missing: offer to run ALL owner tests, with and without the owner mark, and every suite of `project.json`, not only the tests of one script. One saved file makes all results old. Record each file under the suite that its tests belong to: `record-tests <suite> <file>`
- When a test passes, the owner removes its owner mark. When the script is done, offer to commit it.

## Tune: the owner changes the numbers

- Before the first tweak: Run and record every whole suite, as in the build. A tweak in a code file makes the results old, so do it again after the last one. Old results during tuning are run again before `/finish-phase`, and a failing owner test sends the phase back to build.
- Say which setting influences which target. Never say or change a value.
- For each tweak ask for the change and the prediction before the run. Then record it:
  - `predicted`: where the owner expects the measured value of the target to go: `up`, `down` or `none`.
  - `before`, `after`: that measured value, before and after the change. Never the value of the setting. Example: "Moth.speed 3 to 4" made the wins go from 35 to 45, so before=35 and after=45.

```
bash "${CLAUDE_PLUGIN_ROOT}/scripts/run.sh" log tweak change=- predicted=<up|down|none> target=<id> before=<number> after=<number> phase=N <<'END'
<the change, in the owner's words>
END
```

- Record what was measured: `log measure target=<id> value=<number>`
- At most 6 rounds. For a target that is still missed the owner gives a reason:

```
bash "${CLAUDE_PLUGIN_ROOT}/scripts/run.sh" log reason target=<id> text=- phase=N <<'END'
<the reason, in the owner's words>
END
```

- A target changes only through the owner: edit the plan by hand, then `/approve-phase N change: <reason>`.

## Wrap-up: in this order

The owner's answers come first, so say nothing about a concept before them. If the wrap-up has begun, keep what is there and go on with the first missing question, rating, entry or lesson.

1. Ask the planned questions, one by one. Save each answer at once under `### <question id>` in *Answers*, in the owner's words, unchanged. Do not correct them. Do not show the points.
2. Name which points are missing, without giving the answer, and ask again. Add the new answer below the first one, after a line `After a hint:`.
3. Rate each concept by the points: `on my own` (all without a hint), `with help` (all after hints), `can't yet`. Record it: `log rating concept=<id> rating="<rating>"`. A concept at `can't yet` is gone over and asked again.
4. Write the *Concept summary*, one `### <concept name>` for each: the idea and its usual name, how this game does it, what it resembles in the owner's background, the alternative not chosen, something that went wrong here.
5. Ask for 3 to 5 *Lessons*, at least one about the process and one thing to do differently. Save them as list items in the owner's words. Ask for the two sentences of *Process*: `Surprised me:` and `Differently:`.
6. Run `bash "${CLAUDE_PLUGIN_ROOT}/scripts/run.sh" status N`. It shows the scorecard, or what is still open. Show it. Old results or tests not run: run and record every whole suite first. If nothing is open, remind the owner to commit their code and the wrap-up, or offer to do it. Then ask the owner to type `/finish-phase N`. It changes the two phase files: say that they are to be committed after `/finish-phase N` and before the merge.
