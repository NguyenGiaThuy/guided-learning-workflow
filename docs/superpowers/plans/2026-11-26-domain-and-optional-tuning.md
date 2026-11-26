# The project's field, its words, and optional tuning: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `project.json` gets `domain`, `words` and `tuning`; every fixed text uses the project's words, and a project without tuning finishes phases without targets.

**Architecture:** The settings check gains optional keys. `Project` exposes `words`, `tuning` and `domain` with defaults. Every text function in `texts.py` that says "game" or "balance" takes a `Words` value; callers pass `project.words`. Tuning off only lifts the "at least one target" rule and hides tune lines when a phase has no target; the state machine is unchanged.

**Tech Stack:** Python 3.9+ standard library, bash, Claude Code plugin (skills, hooks). Tests: `python -m unittest discover -s tests -v`.

**Spec:** `docs/superpowers/specs/2026-11-26-domain-and-optional-tuning-design.md`

## Global Constraints

- Python 3.9+, standard library only. All owner-facing text lives in `scripts/gl/texts.py`.
- Defaults when a key is missing: `words` = `{"project": "game", "targets": "balance"}`, `tuning` = `true`, `domain` = none. A project without the keys gives byte-identical texts to today's, except the neutral command descriptions (Task 2).
- `domain`: a string on one line, 1 to 100 characters, no spaces around it.
- Each word: matches `^[A-Za-z0-9-]+( [A-Za-z0-9-]+)?$`, 1 to 20 characters. `words` is an object whose keys are only `project` and `targets`; one may be missing.
- `tuning`: a JSON boolean (not 0/1, not a string).
- A sentence that starts with a word capitalizes only its first letter.
- Public repository: no person's name, email or real game in files. Lantern Keeper stays the fake game.
- Branch `build-0.2.0`; commit after each task; never push; do not change git config.
- Version 0.2.0 in `.claude-plugin/plugin.json`, CHANGELOG entry `## 0.2.0 (unreleased)`.

## Review Focus

- `words` with an unknown key (`{"project": "app", "player": "user"}`) is an error naming `words`, not a silent pass. Test in Task 1.
- `tuning: "false"` (a string) is an error, never read as true or false. Test in Task 1.
- A rehearsal in a project with other words: the fake project's texts say "game"/"balance", the lines about the real project use the real words. Test in Task 2.
- `tuning: false` with a plan that has targets: the phase tunes exactly as today. Test in Task 3.
- A word that is exactly 20 characters is accepted, 21 refused; two spaces between words refused. Test in Task 1.

---

### Task 1: The three settings

**Files:**
- Modify: `scripts/gl/settings.py`, `scripts/gl/project.py`, `scripts/gl/texts.py` (setup key descriptions), `scripts/gl/setup.py`
- Test: `tests/test_project.py`, `tests/test_setup.py`, `tests/test_hooks.py`

**Interfaces:**
- Produces: `texts.Words` (a `collections.namedtuple("Words", "project targets")`), `texts.DEFAULT_WORDS = Words("game", "balance")`; `Project.words -> Words`, `Project.tuning -> bool`, `Project.domain -> str | None` (properties, defaults when missing or when the settings are broken); `settings.OPTIONAL` (dict key -> check) next to the existing `_CHECKS`.

- [ ] **Step 1: Failing tests**
  - `test_project.py`: `test_defaults_without_the_keys` (`words == Words("game", "balance")`, `tuning is True`, `domain is None`); `test_words_and_tuning_are_read` (`{"words": {"project": "app"}, "tuning": false, "domain": "web backend in Go"}` gives `Words("app", "balance")`, `False`, the domain).
  - `test_setup.py` (via `settings.problems`): `test_optional_keys_are_known` (no `setup_unknown` for them); `test_bad_optional_values` with each of `{"tuning": "false"}`, `{"tuning": 1}`, `{"words": "app"}`, `{"words": {"project": "app", "player": "user"}}`, `{"words": {"project": ""}}`, `{"words": {"project": "a" * 21}}`, `{"words": {"targets": "two  spaces"}}`, `{"words": {"project": "x\ny"}}`, `{"domain": ""}`, `{"domain": "x" * 101}` -> exactly one problem, naming the key; `test_edges_accepted`: `"a" * 20`, `"web app"`, `"real-time"`, a 100-character domain -> no problem; setup refuses a settings file with `{"tuning": "false"}` and accepts one with all three keys.
  - `test_hooks.py`: `test_bad_words_in_project_json_deny_edits` (PreToolUse on a code file denies and the reason names `project.json` and `words`, like the existing wrong-type test of I7).
- [ ] **Step 2:** Run `python -m unittest test_project test_setup test_hooks` from `tests/`. Expected: the new tests fail.
- [ ] **Step 3:** Implement. Optional keys are checked only when present, through the same `wrong()` path, so hooks, CLI and setup report them as they report other wrong values today. `texts._SETUP_KEYS` gets descriptions for `domain`, `words`, `tuning` (used by `setup_key`).
- [ ] **Step 4:** Run the same tests, then the full suite. Expected: OK.
- [ ] **Step 5:** Commit `feat: domain, words and tuning in project.json`.

### Task 2: The fixed texts take the project's words

**Files:**
- Modify: `scripts/gl/texts.py`, `scripts/gl/plan.py`, `scripts/gl/scorecard.py`, `scripts/gl/setup.py`, `scripts/gl/rehearsal.py`, `scripts/gl/commands.py`, `skills/setup-learning/SKILL.md` (frontmatter description only), `templates/README.md` (commands table and settings row), `docs/design.md` (Descriptions table row)
- Test: `tests/test_render.py`, `tests/test_commands.py`, `tests/test_scorecard.py`, `tests/test_setup.py`, `tests/test_rehearsal.py`, `tests/test_skills.py`

**Interfaces:**
- Consumes: `texts.Words`, `texts.DEFAULT_WORDS`, `Project.words` (Task 1).
- Produces, all in `texts.py` (each replaces the old constant or gains the last parameter):
  - `gap_no_target(words) -> str`: `"No %s target." % words.targets` (replaces `GAP_NO_TARGET`)
  - `planning_started(n, plan, md, words)`: "balance targets" becomes `"%s targets" % words.targets`
  - `score_balance(met, total, words)`: `"%s: %d/%d targets met." % (capitalized words.targets, met, total)`
  - `setup_settings_by_hand(words)`: replaces `SETUP_SETTINGS_BY_HAND`, "This %s was set up before, ..."
  - `setup_key(key, given, words)`: "a folder of the %s", "a list of code folders of the %s"
  - `setup_elsewhere(root, words)`, `setup_ignored(words)` (replaces `SETUP_IGNORED`), `rehearsal_short(run, words)`, `rehearsal_rules(run, script, words)`: "game" becomes `words.project`
  - `COMMANDS["setup-learning"]` = `("step 0: once per project", "", "Step 0, once per project: set up guided learning in this project.")`
  - `capitalized(word) -> str`: first letter upper, the rest unchanged.

- [ ] **Step 1: Failing tests:** for each function above, one test with `DEFAULT_WORDS` that equals today's text exactly (copy today's string into the test), and one with `Words("app", "performance")` (e.g. `gap_no_target(Words("app", "performance")) == "No performance target."`, `score_balance(2, 3, Words("app", "performance")) == "Performance: 2/3 targets met."`). `test_rehearsal.py`: `test_real_words_in_the_lines_about_the_real_project` (real project with `{"words": {"project": "app"}}`, rehearsal on: `rehearsal_short` and the rules say "app"; a plan gap of the fake project says "No balance target."). `test_skills.py` and `test_render.py` already compare the descriptions with `COMMANDS`; they fail until the skill frontmatter, `docs/design.md` and `templates/README.md` say "once per project". Add `test_no_game_word_left` in `test_render.py`: no string in `texts.py` other than in `DEFAULT_WORDS` contains the whole word "game" or "balance" (search the module source, ignoring comments).
- [ ] **Step 2:** Run `python -m unittest test_render test_commands test_scorecard test_setup test_rehearsal test_skills` from `tests/`. Expected: the new tests fail.
- [ ] **Step 3:** Implement. Callers pass `project.words` of the project the text is about: in a rehearsal, the fake project's words for its plan, status and scorecard; the outer project's words for `rehearsal_short` and `rehearsal_rules`; in setup, the words of the settings being written (or `DEFAULT_WORDS` when they cannot be read).
- [ ] **Step 4:** Run the same tests, then the full suite. Expected: OK.
- [ ] **Step 5:** Commit `feat: the fixed texts use the words of the project`.

### Task 3: Tuning off

**Files:**
- Modify: `scripts/gl/plan.py`, `scripts/gl/texts.py`, `scripts/gl/render.py`, `scripts/gl/scorecard.py`, `scripts/gl/commands.py`
- Test: `tests/test_commands.py`, `tests/test_render.py`, `tests/test_scorecard.py`, `tests/test_whole_phase.py`

**Interfaces:**
- Consumes: `Project.tuning`, `Project.words`, `texts.gap_no_target`, `texts.planning_started` (Tasks 1, 2).
- Produces: `texts.planning_started(n, plan, md, words, tuning)` (the targets clause is left out when `tuning` is false); `plan.plan_gaps(project, n)` unchanged in signature.

- [ ] **Step 1: Failing tests**
  - `test_commands.py`: `test_no_target_is_no_gap_with_tuning_off`; `test_a_target_is_still_checked_with_tuning_off` (a target without `measure` is the same gap as today); `test_planning_text_without_targets` (`tuning: false`: the text of `/start-phase` names no targets).
  - `test_render.py`: `test_then_line_without_targets` (a phase in build with no target: `Then: wrap-up`); `test_then_line_with_targets_and_tuning_off` (unchanged: `Then: tune (0 of 1 target), wrap-up`).
  - `test_scorecard.py`: `test_no_balance_or_predict_line_without_targets_and_tweaks`; `test_lines_stay_with_targets` (tuning off, one target: both lines as today).
  - `test_whole_phase.py`: `test_a_whole_phase_without_tuning` (git repository, `tuning: false`, a plan with no targets, approve, build, hand-over, owner code, tests recorded, the status goes from build straight to wrap-up, finish, closing text; the scorecard in `phase-1.md` has no balance and no predict line).
- [ ] **Step 2:** Run those test files. Expected: the new tests fail.
- [ ] **Step 3:** Implement. The `Then:` line leaves out the tune step when `st.targets_total == 0`. The scorecard leaves out balance and predict when the plan has no target and no tweak was logged.
- [ ] **Step 4:** Run the same tests, then the full suite. Expected: OK.
- [ ] **Step 5:** Commit `feat: tuning can be switched off`.

### Task 4: Skills, templates and documents

**Files:**
- Modify: `skills/setup-learning/SKILL.md`, `skills/start-phase/SKILL.md`, `skills/summarize-phase/SKILL.md`, `skills/build-phase/SKILL.md`, `templates/claude-md-section.md`, `templates/README.md`, `README.md`, `docs/design.md`, `CHANGELOG.md`, `.claude-plugin/plugin.json`
- Test: `tests/test_skills.py`, `tests/test_readme.py`

- [ ] **Step 1: Failing tests** in `test_skills.py`: `test_setup_asks_for_the_new_settings` (the setup skill's settings table has rows `domain`, `words`, `tuning`, and its JSON example contains the three keys); `test_skills_say_project_not_game` (no skill or template contains the whole word "game" except where it names the example of a game domain, which is a line containing `"game"` in quotes); `test_start_phase_targets_follow_tuning` (the start-phase skill says targets are planned only when `tuning` is not false); `test_summarize_skips_tuning_without_targets`. `test_readme.py`: the README documents `domain`, `words`, `tuning`; `plugin.json` version is `0.2.0` and CHANGELOG has `## 0.2.0 (unreleased)`.
- [ ] **Step 2:** Run `python -m unittest test_skills test_readme` from `tests/`. Expected: the new tests fail.
- [ ] **Step 3:** Write the texts as the spec says (sections "/setup-learning", "Tuning off", "Wording in the AI's instructions"): the setup skill asks for the three settings in its single message, each with a suggestion and reason; the engine question only for a game; skills tell the AI to read `domain` and `words` from `project.json` and use them with the owner. README: a section "Other fields than games" with the three settings. `docs/design.md`: the settings table gets the three keys, and the tuning rule. Run `claude plugin validate .` (claude.exe of the VS Code extension 2.1.332).
- [ ] **Step 4:** Run the same tests, then the full suite, then `claude plugin validate .`. Expected: OK, validation passed.
- [ ] **Step 5:** Commit `docs: setup asks for the field, its words and tuning`.

### Task 5: Repeat cases for other words and no tuning

**Files:**
- Modify: `tests/repeat/cases.py`
- Test: `tests/test_repeat.py`

**Interfaces:**
- Consumes: `texts.previous_open`, `texts.Words`, `Project.words`, the closing and finish judges of `cases.py`.

- [ ] **Step 1: Failing tests** in `test_repeat.py`: `ListTests.test_the_cases_of_the_brief` gains `"start blocked, other words"` and `"finish without tuning"`; judge tests for both in the style of `StatusTests` (passed with the expected text, failed without it); `DamageTests` cover both (locked scripts and state are guarded).
- [ ] **Step 2:** Run `python -m unittest test_repeat` from `tests/`. Expected: fail.
- [ ] **Step 3:** Add the cases. "start blocked, other words": the project of `_phase_1_open` with `{"words": {"project": "app", "targets": "performance"}}`; `/start-phase 2`; judged by `_blocked(texts.previous_open(2))`, plus a check that no hook text in the run contains the whole word "game". "finish without tuning": like `finish`, with `tuning: false` and a plan without targets; judged by `_finished`.
- [ ] **Step 4:** Run `test_repeat`, then the full suite. Expected: OK.
- [ ] **Step 5:** Commit `test: repeat cases for other words and no tuning`.

### Task 6: Repeat runs and the record

**Files:**
- Create: `docs/repeat-runs/0.2.0.md`
- Modify: `README.md` (the "Tested:" line)

- [ ] **Step 1:** Make a clean clone of `build-0.2.0` in the scratchpad (the runner checks the plugin hash). Run there: `python tests/repeat/run.py --model sonnet --times 3 --jobs 4 --raw <empty folder>`. Expected: every release row 3 of 3, exit 0. If a row is not 3 of 3: stop, look at its raw output, report to the owner. A fix of the plugin means all rows again.
- [ ] **Step 2:** Save the table in `docs/repeat-runs/0.2.0.md` in the form of `0.1.0.md` (heading line with plugin hash, Claude Code version, model, jobs, date; release table; extra table). Remove local paths and the user name from the notes. Update the README "Tested:" line: Sonnet, each enforced behavior 3 times, link to the new table.
- [ ] **Step 3:** Full suite once more. Expected: OK.
- [ ] **Step 4:** Commit `docs: repeat runs of 0.2.0, 3 times with Sonnet`. Then the owner rehearses once in the VS Code panel; do not push.
