---
name: start-phase
description: "Step 1: begin PLANNING phase N with the AI. Checks that the phase before it is finished. Writes no code."
argument-hint: "<N> [skip: reason]"
disable-model-invocation: true
---

A hook has already checked this command and made the files. Its text is in your context ("Phase N is being planned ..."), with what is carried over. Do not check again.

If there is no such text, guided learning is not set up here, or its hooks do not run. Say that `/setup-learning` comes first, and stop.

Plan the phase with the owner. Write only `phase-N.plan.json` and `phase-N.md`, in the folder the hook names. Write no code. Do not edit `phase-N.json`.

## Talk first

- Read the design of the game, *Notes for later* of the phases before, and the carried items. Give each carried item a place in this phase, or agree to drop it.
- Ask what the phase should do and which concepts the owner wants to learn. Agree on each block of the plan before the next one.
- Propose a branch for the phase, in the project folder and without a worktree. The owner creates it or agrees that you do. It must be checked out before the approval.

## The plan

```json
{"phase": 2,
 "concepts": [{"id": "ai", "name": "Enemy AI"}],
 "parts": [{"name": "Moths", "tasks": ["Shells and tests", "Moth art"], "scripts": [1]}],
 "scripts": [{"id": 1, "name": "Moth", "path": "src/Moth.cs", "concept": "ai",
              "todos": ["1.1", "1.2"], "tests": ["MothTests.Turns"]}],
 "targets": [{"id": "wins", "text": "Average player wins", "measure": "20 bot runs",
              "settings": ["Moth.speed"], "min": 40, "max": 60}],
 "questions": [{"id": "q1", "concept": "ai", "text": "How does it choose a target?",
                "points": ["nearest", "in range"]}]}
```

- **concepts**: what the phase teaches.
- **scripts**: 3 to 5, the core script of each concept. The owner writes these. Each has a path, a concept, TODO numbers `<script id>.<step>` as text, and the names of its tests.
- **parts**: AI work, then the owner scripts it prepares. Each part has at least one task, and each script is in exactly one part. A part is as much as the AI builds in one go. The last part may have no scripts.
- **targets**: balance targets, at least one. Each has a measure, the settings that influence it, and `min` or `max` or both, as numbers. Set them now, not after seeing a result.
- **questions**: at least one per concept, for the wrap-up. Each has points that an answer must contain. Agree on the questions. Write the points without showing them: the owner should not read them before the wrap-up.

Put decisions, surprises and open questions under *Notes for later* in `phase-N.md`.

## With Superpowers

If its skills are there, plan with `brainstorming` and `writing-plans`. One plan document is one part. Owner work goes under `### Owner N`, and work for agents under `### Task N`. Ask for the execution method and note it under *Notes for later*. Choosing it starts nothing.

## The end

Show the plan without the points. Name what is undecided. Then end with the next command:

`/approve-phase N`: the owner types it. It checks the plan and locks it. Nothing is built before `/build-phase N`.
