---
name: approve-phase
description: "Step 2: you ACCEPT the plan of phase N and lock its targets. Writes no code."
argument-hint: "<N> [change: reason]"
disable-model-invocation: true
---

A hook has already checked the plan and recorded what the owner accepts. Its text is in your context. Do not check again.

If there is no such text, guided learning is not set up here, or its hooks do not run. Say that `/setup-learning` comes first, and stop.

1. Show the text of the hook.
2. Explain in a few sentences what it means:
   - Accepted: the plan and its targets are locked. The branch that is checked out now becomes the branch of the phase. The first `/build-phase` sets it again, to the branch that is checked out then.
   - Change accepted: the new plan counts, and the reason is kept.
   - A note about few scripts is advice, not an error.
   - Approved already: nothing has changed.
3. Say that from now on a target changes only when the owner edits the plan by hand and types `/approve-phase N change: <reason>`.
4. End with the next command that the text names. The owner types it.

Build nothing and write no file. If there are plan documents, do not begin with their tasks, also if an execution method was chosen.
