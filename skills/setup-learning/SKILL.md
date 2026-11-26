---
name: setup-learning
description: "Step 0, once per project: set up guided learning in this project."
disable-model-invocation: true
---

Set up guided learning in this project. The working folder is the project's root, also if it is still empty. Do not look for a project elsewhere. The script checks the settings and writes the files. You find out the settings.

## If `.claude/learning/project.json` exists

The project is set up. Say so. Run the script with that file, to add what is missing:

`bash "${CLAUDE_PLUGIN_ROOT}/scripts/run.sh" setup .claude/learning/project.json`

If CLAUDE.md has no section of guided learning, ask whether to add it, and use the flag of step 3. Show the output of the script and stop. A hook may report that `config.json` changed: the script added it, so tell the owner that.

## Otherwise

1. Look at the folder: field, language, framework or engine, code folders, test framework, existing docs. In a new project, suggest the usual folders and ask for the field and language too. Ask for the engine only when the words are `"project": "game"`. Then ask the owner for all settings in one message, with a suggestion and its reason for each. Say what each one is for. Write nothing before the owner answers.

   | Setting | What it is |
   |---|---|
   | `docs` | folder for the phase files, for example `Docs/learning` |
   | `code` | list of all folders with code of the project and its tests. The hooks protect code only there. |
   | `extensions` | list of file extensions of the code, like `.cs` |
   | `ownerMark` | text that keeps an owner test out of normal runs, in NUnit `[Explicit("Owner")]` |
   | `suites` | list of names of the test suites. Their results must be NUnit 3 or JUnit XML, or lines `name,pass` and `name,fail`. |
   | `background` | what the owner has programmed so far. Hints are written for that. |
   | `domain` | the field of the project in the owner's words, like `web backend in Go`. Hints, examples and the questions of a phase are written for that. Suggest it from what the folder shows. |
   | `words` | two words for the texts of the script: `project`, what the thing is called (`"game"`, `"app"`, `"model"`, `"service"`), and `targets`, the word before "targets" (`"balance"`, `"performance"`, `"quality"`). Each is one or two words of letters, digits or hyphens, starting with a letter or digit, at most 20 characters. Suggest them from the field. |
   | `tuning` | `true` or `false`: whether a phase ends with tuning, where the owner changes numbers towards measured targets and predicts each result. Suggest `true` where the field has numbers worth tuning (balance, speed, accuracy), else `false`. |

   Ask also: may a short section be added to `CLAUDE.md`? It says that the AI leaves `TODO(owner)` alone, and how Superpowers is used in a phase. Offer to show it: `${CLAUDE_PLUGIN_ROOT}/templates/claude-md-section.md`.

2. Write the answers as JSON, in the owner's words, to a temporary file outside of the project. Use its absolute path:

   ```json
   {"docs": "Docs/learning", "code": ["src"], "extensions": [".cs"],
    "ownerMark": "[Explicit(\"Owner\")]", "suites": ["Unit"], "background": "C# web developer",
    "domain": "2D platformer in Unity", "words": {"project": "game", "targets": "balance"}, "tuning": true}
   ```

3. In the root folder of the project run:

   `bash "${CLAUDE_PLUGIN_ROOT}/scripts/run.sh" setup "<absolute path of the file>"`

   Add `--claude-md` only if the owner agreed to the section. If the script refuses, mend the settings with the owner and run it again. Do not write the files yourself.

4. Show the output of the script, with the next command. Say that a new chat is needed for the status line. Delete the temporary file. Do not start a phase.
