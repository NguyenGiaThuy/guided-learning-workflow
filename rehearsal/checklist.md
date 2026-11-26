# Rehearsal checklist

Lantern Keeper is a fake game: you can try everything, and your real game stays as it is. The fake project is the folder `.claude/learning/rehearsal` of your game, and all files named below are in it. You edit its code by hand in the editor, like your own.

- Go through the lines in order. Keep the AI on the normal model you work with.
- *Script*: the script ticks the line when it sees the result. *Owner*: you compare, and say "run `rehearse check` with the id" if it matches.
- "Say: run `rehearse ...`" means: ask the AI in the chat to run that command of `learning.py`. It simulates tests, the merge and the branch.
- "Run `rehearse report`" shows what is ticked. The same report is kept as `.claude/learning/rehearsal-reports/run-N.md`.
- A line that does not match is a defect of the workflow, also if the script ticked it.
- Save `.claude/learning/config.json` again to start from the beginning. Set it to `{"rehearsal": false}` to go back to your game.

| Id | Covers | Type | Expect | Ticked by |
|---|---|---|---|---|
| `status-line` | - | Open a new chat: `/summarize-phase 2` | The answer begins with `Learning hooks: on (REHEARSAL run N, ...)`. N is one more than last time. (The terminal shows the same line when the chat opens; the VS Code panel does not.) | owner |
| `resume-half` | resuming at 50% | `/summarize-phase 2` | 2 of 5 TODOs done, next is TODO 1.3 of the moth. The AI explains it and waits. | script |
| `resume-closed` | resuming after closing the chat in the middle | Ask something about TODO 1.3 and close the chat while the AI answers. Open a new chat: `/summarize-phase 2` | The same state as before. The AI does not ask what was done. | script |
| `ask-todo` | asking the AI to write a TODO | Write TODO 1.3 of the moth for me, in the file of the rehearsal. | The AI does not write it. It offers help in levels. | owner |
| `edit-locked` | asking the AI to write a TODO | I want to see the refusal: try once to add an empty line to .claude/learning/rehearsal/src/Moth.cs with your edit tool. | The edit is refused: `src/Moth.cs is locked`. | script |
| `build-owners-turn` | `/build-phase` on the owner's turn | `/build-phase 2` | Blocked: it is the owner's turn, with the open TODO and the failing test. | script |
| `finish-early` | `/finish-phase` too early | `/finish-phase 2` | Blocked, with everything that is open. | script |
| `start-early` | `/start-phase` too early | `/start-phase 3` | Blocked: phase 2 is not finished. The line shows how to skip. | script |
| `wrong-branch` | the wrong branch | Say: run `rehearse branch`. Then `/summarize-phase 2`. Then say: run `rehearse branch stage-2`. | It says that main is checked out instead of stage-2, and stops. | script |
| `todo-failing` | a TODO removed with a failing test | Delete the line with `TODO(owner 1.3)` in src/Moth.cs and save. Say: run `rehearse fail`. Then `/summarize-phase 2` | Moth is in progress and not done, with the failing tests. | script |
| `build-resumed` | `/build-phase` resumed in the middle | Delete the line with the owner mark in src/Tests/MothTests.cs and save. Say: run `rehearse pass`. Then `/build-phase 2`. The AI does a task and asks you about the light. Do not answer: close the chat. Open a new chat: `/build-phase 2`, and do not answer yet. | In the new chat the AI does not do the first task again. It goes straight to the question about the light, and waits. | script |
| `hand-over-missing` | a hand-over with a missing TODO | Delete the line with `TODO(owner 2.2)` in src/Lantern.cs and save. Answer in the same chat: Yes, a straight line. First run `rehearse fail`, then hand over. Repair nothing, I want to see what is missing. | Not handed over. Only one thing is missing: `TODO(owner 2.2) is not in src/Lantern.cs`. | script |
| `hand-over` | - | Put the line back and save. Say: run `rehearse fail`, then `hand-over 2`. | Phase 2, part 2 handed over. Your turn: 1 script, 2 TODOs. | script |
| `finish` | finishing | Delete the lines with the TODOs in src/Lantern.cs and with the owner marks in src/Tests/LanternTests.cs, and save. Say: run `rehearse pass`. Open a new chat: `/summarize-phase 2`. Do the tuning with invented numbers, without editing the code. (If you do edit it, say: run `rehearse pass` again.) When the AI asks for a new chat, open one, type `/summarize-phase 2` and do the wrap-up. Then `/finish-phase 2` | Tuning comes first, then the wrap-up in a new chat. Your answers stand unchanged in Docs/learning/phase-2.md. At the end: phase 2 is done. | script |
| `closing-text` | finishing | Nothing: look at the same answer. | It ends with the closing text: saved where, branch not merged, what is carried, and the next command. | script |
| `start-unmerged` | `/start-phase` too early | `/start-phase 3` | Blocked: phase 2 is done, but its branch stage-2 is not merged. | script |
| `start-new-chat` | `/start-phase` in a new chat | Say: run `rehearse merge`. Open a new chat: `/start-phase 3` | Phase 3: planning would start here. What is carried over from phase 2 is listed. The AI plans nothing. | script |
| `build-unapproved` | `/build-phase` before approval | `/build-phase 3` | Blocked: the plan is not approved, with what is missing. | script |
| `edit-unapproved` | an edit of code before approval | I want to see the refusal: try once to add an empty line to .claude/learning/rehearsal/src/Lantern.cs with your edit tool. | The edit is refused: phase 3 is still being planned. | script |
| `start-skip` | `/start-phase` with a skip | `/start-phase 4 skip: trying it out` | Phase 3 was skipped: trying it out. Phase 4: planning would start here. Carried over: the plan of phase 3 is not approved yet. | script |
