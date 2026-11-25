---
name: build-phase
description: "Step 3: the AI WRITES the boilerplate (TODO shells, tests, the rest), or resumes it."
argument-hint: "[N]"
disable-model-invocation: true
allowed-tools: Bash(bash *run.sh* status*), Bash(bash *run.sh* log task *), Bash(bash *run.sh* record-tests *), Bash(bash *run.sh* hand-over*), Bash(bash *run.sh* rehearse *)
---

The status of the phase:

!`bash "${CLAUDE_PLUGIN_ROOT}/scripts/run.sh" status $ARGUMENTS`

If it says that guided learning is not set up, say that `/setup-learning` comes first, and stop. If it says that there is no phase, show that and stop.

A hook has already checked that it is the AI's turn. Its text is in your context: the part, its tasks (done or open), and its owner scripts. Do not check again. If there is no such text, the hooks do not run: say so and stop.

If the text says REHEARSAL, its rules come first: the other folder, no git, and simulated tests in place of real ones. Run `rehearse fail` or `rehearse pass` only when the owner says so; if results are missing, ask.

Do the open tasks of this part only. Read `phase-N.plan.json` and *Notes for later* in `phase-N.md` first. Both are in the folder `docs` of `.claude/learning/project.json`, like the owner mark and the owner's background.

## The owner scripts

- Write each one as a shell: fields, signatures, and the planned TODOs in their file, each as a comment `TODO(owner S.T)` in the style of the language, like `// TODO(owner 1.2)`. Use exactly the numbers of the plan.
- The shell compiles and does nothing harmful.
- A TODO says what must be true, not each line. Add pseudo code and hints. Explain the engine and game ideas, at the level of the owner's background.
- Never write the code behind a TODO, also not in another file, a test, a commit or the chat.

## The tests

- Write the tests first, with the names of the plan and the owner mark of `project.json`, so that normal runs skip them.
- Run the owner tests of this part on purpose, with the mark. They must compile and fail.
- Run every suite of `project.json`, as a whole, after the last code change. All other tests must pass. A suite with nothing to run cannot be recorded: add a smoke test to it.
- Record each result file, from the normal runs and from the owner tests, under the suite of `project.json` that the test belongs to:

  `bash "${CLAUDE_PLUGIN_ROOT}/scripts/run.sh" record-tests <suite> <file>`

- If you cannot run the tests, ask the owner to run them and to give you the result file.

## While you work

- After each task: `bash "${CLAUDE_PLUGIN_ROOT}/scripts/run.sh" log task part=<number> index=<number> phase=N`. Both numbers count from 1, as the hook text shows them.
- Commit after each task, on the branch of the phase. Include the phase files.
- Add decisions, surprises and what went wrong to *Notes for later*.
- Do not edit `phase-N.json` or the plan. If the plan is wrong, tell the owner what should change. The owner edits it and types `/approve-phase N change: <reason>`.
- With Superpowers: use the execution method that *Notes for later* names, with the plan document of this part. Agents get only `### Task N`, never `### Owner N`. Tell each of them to leave `TODO(owner)` alone.

## The end

When all tasks of the part are done:

`bash "${CLAUDE_PLUGIN_ROOT}/scripts/run.sh" hand-over N`

If it lists what is missing, do that and run it again. If something needs the owner, ask. When it succeeds, commit, show its text word for word at the end of your answer, and stop. Start no other part.
