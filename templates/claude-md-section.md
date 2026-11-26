<!-- guided-learning:start -->
## Guided learning

The owner learns by writing the key scripts of this project. The guided-learning plugin keeps the state. The owner types its commands; you never start them.

- Leave `TODO(owner S.T)` alone. The owner replaces it with their own code. Do not fill it in, remove it or move it, also not by a shell command or a subagent.
- Help with owner code only at the level the owner asks for. A review names the problem or asks a question. It does not rewrite.
- Write no code of a phase before `/approve-phase` and `/build-phase`.
- Records go through the script of the plugin. Do not edit `phase-N.json`, an approved plan, or `project.json` and `config.json` of `.claude/learning`.

With Superpowers, these rules come before its skills:

| Skill | Rule |
|---|---|
| `writing-plans` | Owner work goes under `### Owner N`. Agents are only given `### Task N`. Planning ends with `/approve-phase`, and building starts with `/build-phase`. Choosing an execution method does not start it. |
| `subagent-driven-development`, `executing-plans` | A plan is one part and ends with the hand-over. The next plan starts with the next `/build-phase`, so no plan has to pause. |
| `test-driven-development`, `verification-before-completion` | Owner tests are outside normal runs. For the shell, the expected result is that they compile and fail. |
| reviews | `TODO(owner)` is intended. Review the shell, the tests and the hints. |
| `systematic-debugging` | For owner code: find the cause, then help at the level asked for. |
| `using-git-worktrees` | Use a branch in the project folder, no worktree, so the owner can write in the open editor. |
| `finishing-a-development-branch` | The wrap-up and `/finish-phase` come first. |
<!-- guided-learning:end -->
