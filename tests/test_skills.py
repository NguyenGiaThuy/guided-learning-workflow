import json
import re
import tempfile
import unittest
from pathlib import Path

import helpers
import learning
from gl import hooks, log, texts

ROOT = Path(__file__).resolve().parent.parent
SKILLS = ROOT / "skills"
WITH_STATUS = ("build-phase", "summarize-phase")
STATUS_LINE = '!`bash "${CLAUDE_PLUGIN_ROOT}/scripts/run.sh" status $ARGUMENTS session=${CLAUDE_SESSION_ID}`'
RUN = 'bash "${CLAUDE_PLUGIN_ROOT}/scripts/run.sh" '
FREE_TEXT = ("change", "text")   # fields with the owner's words


def read(name):
    return (SKILLS / name / "SKILL.md").read_bytes().decode("utf-8")


def frontmatter(text):
    """The keys of the frontmatter; a value in quotes is JSON, which is also YAML."""
    head = re.match(r"---\n(.*?)\n---\n", text, re.S).group(1)
    found = {}
    for line in head.split("\n"):
        key, value = line.split(": ", 1)
        found[key] = json.loads(value) if value.startswith('"') else value
    return found


def code(text):
    """The commands of a skill: code spans, and the lines of code blocks."""
    body = text.split("\n---\n", 1)[1]
    blocks = re.findall(r"(?ms)^```[a-z]*\n(.*?)^```", body)
    spans = re.findall(r"`([^`\n]+)`", re.sub(r"(?ms)^```.*?^```", "", body))
    return spans + [line for b in blocks for line in b.split("\n")]


def calls(text):
    """The calls of the script in a skill, with or without run.sh in front, as lists of words."""
    found = []
    for c in code(text):
        if c.startswith(RUN):
            found.append(c[len(RUN):].split())
        elif re.match(r"(log|record|hand|setup|status|version|hook)(-[a-z]+)?( |$)", c):
            found.append(c.split())
    return found


class SkillTests(unittest.TestCase):
    def each(self, check):
        for name in texts.COMMANDS:
            with self.subTest(name):
                check(name, read(name))

    def test_one_skill_per_command(self):
        self.assertEqual({p.parent.name for p in SKILLS.glob("*/SKILL.md")}, set(texts.COMMANDS))

    def test_descriptions_and_hints_match(self):
        def check(name, text):
            head = frontmatter(text)
            _, hint, description = texts.COMMANDS[name]
            self.assertEqual(head["name"], name)
            self.assertEqual(head["description"], description)
            self.assertEqual(head.get("argument-hint", ""), hint)
            self.assertEqual("argument-hint" in head, bool(hint))
        self.each(check)

    def test_hints_are_text_and_no_yaml_list(self):
        def check(name, text):
            for line in re.findall(r"(?m)^(?:description|argument-hint): .*$", text):
                self.assertRegex(line, r'^[a-z-]+: ".*"$')
        self.each(check)

    def test_all_are_owner_only(self):
        self.each(lambda name, text: self.assertEqual(frontmatter(text).get("disable-model-invocation"), "true"))

    def test_at_most_80_lines_and_lf(self):
        def check(name, text):
            self.assertLessEqual(len(text.splitlines()), 80)
            self.assertNotIn("\r", text)
        self.each(check)

    def test_status_is_inserted_where_the_phase_goes_on(self):
        def check(name, text):
            self.assertEqual(text.split("\n").count(STATUS_LINE), int(name in WITH_STATUS))
            self.assertEqual(text.count("!`"), int(name in WITH_STATUS))
            allowed = frontmatter(text).get("allowed-tools", "")
            self.assertEqual("Bash(bash *run.sh* status*)" in allowed, name in WITH_STATUS)
        self.each(check)

    def test_a_missing_project_names_setup(self):
        self.each(lambda name, text: self.assertIn("/setup-learning", text + "/" + name))

    def test_script_calls_exist(self):
        counted = []

        def check(name, text):
            for words in calls(text):
                self.assertIn(words[0], learning.SUBCOMMANDS)
                counted.append(words[0])
        self.each(check)
        self.assertGreaterEqual(set(counted), {"status", "log", "record-tests", "hand-over", "setup"})

    def test_records_have_the_fields_of_the_log(self):
        kinds = set()

        def check(name, text):
            for words in calls(text):
                names = re.findall(r"\b([a-z]+)=", " ".join(words[2:]))
                if words[0] == "log" and names:
                    self.assertEqual(tuple(n for n in names if n != "phase"), log.FIELDS[words[1]], words[1])
                    kinds.add(words[1])
        self.each(check)
        self.assertEqual(kinds, set(log.FIELDS) - {"note"})   # notes go to phase-N.md

    def test_the_owners_words_never_pass_through_the_shell(self):
        def check(name, text):
            for line in code(text):
                fields = re.findall(r"\b(%s)=(\S+)" % "|".join(FREE_TEXT), line)
                self.assertEqual([v for _, v in fields], ["-"] * len(fields), line)
                self.assertEqual("<<" in line, bool(fields), line)
                if fields:
                    self.assertTrue(line.endswith("<<'END'"), line)
            for block in re.findall(r"(?ms)^```[a-z]*\n(.*?)^```", text):
                self.assertEqual(block.count("<<'END'"), len(re.findall(r"(?m)^END$", block)))
        self.each(check)

    def test_commands_named_exist(self):
        def check(name, text):
            for command in re.findall(r"(?<![\w/])/([a-z]+-(?:phase|learning))\b", text):
                self.assertIn(command, texts.COMMANDS)
        self.each(check)


class RuleTests(unittest.TestCase):
    """Rules that a small model got wrong, or that another file relies on."""

    def says(self, name, *phrases):
        text = " ".join(read(name).split())
        for phrase in phrases:
            self.assertIn(phrase, text, name)

    def test_a_tweak_is_about_the_target_and_not_the_setting(self):
        self.says("summarize-phase", "`predicted`: where the owner expects the measured value of the target to go",
                  "`before`, `after`: that measured value, before and after the change. Never the value of the setting")

    def test_wrap_up_can_be_resumed_and_hints_are_marked(self):
        self.says("summarize-phase", "Read the whole `phase-N.md`", "keep what is there", "`After a hint:`")

    def test_one_chat_per_owner_script_and_the_sources(self):
        self.says("summarize-phase", "one owner script", "git history")

    def test_the_owners_work_is_committed_before_finish(self):
        self.says("summarize-phase", "commit their code", "as named")

    def test_superpowers_documents_are_allowed_while_planning(self):
        self.says("start-phase", "with Superpowers, its design and plan documents, outside of the code folders")
        self.says("approve-phase", "The first `/build-phase` sets it again")
        self.assertNotIn("Start no plan document", read("approve-phase"))

    def test_the_owner_says_when_tests_are_simulated(self):
        for name in ("build-phase", "summarize-phase"):
            self.says(name, "simulated", "only when the owner says so")
        self.assertIn("only when the owner says so", texts.rehearsal_rules(1, "x", texts.DEFAULT_WORDS))

    def test_planning_is_resumed_and_saved_in_blocks(self):
        self.says("start-phase", "Read the plan and `phase-N.md` first", "Save each block as soon as it is agreed")

    def test_suites_and_the_settings_file(self):
        self.says("build-phase", "the suite of `project.json` that the test belongs to")
        self.says("setup-learning", "absolute path")


    def test_all_tests_are_run_and_recorded(self):
        self.says("summarize-phase", "run ALL owner tests", "every suite", "One saved file makes all results old",
                  "Before the first tweak", "Run and record every whole suite",
                  "Old results during tuning are run again before `/finish-phase`",
                  "a failing owner test sends the phase back to build")
        self.says("build-phase", "smoke test")

    def test_the_phase_files_are_committed_before_the_merge(self):
        self.assertNotIn("files to commit", read("finish-phase"))   # the closing text says it
        self.says("finish-phase", "no merge, no commit")
        self.says("summarize-phase", "after `/finish-phase N`", "before the merge")

    def test_missing_results_in_a_rehearsal_are_asked_for(self):
        for name in ("build-phase", "summarize-phase"):
            self.says(name, "if results are missing")
        self.says("summarize-phase", "or old, ask the owner")

    def test_where_notes_go(self):
        self.says("summarize-phase", "Notes go there", "`log note`")


class PlanExampleTests(unittest.TestCase):
    def test_the_plan_in_the_skill_has_every_key_the_check_wants(self):
        example = json.loads(re.search(r"```json\n(.*?)\n```", read("start-phase"), re.S).group(1))
        full = helpers.full_plan()
        self.assertEqual(set(example), set(full))
        for key in ("concepts", "parts", "scripts", "targets", "questions"):
            self.assertEqual(set(example[key][0]), set(full[key][0]), key)


class TemplateTests(unittest.TestCase):
    def read(self, name):
        return (ROOT / "templates" / name).read_bytes().decode("utf-8")

    def test_readme_has_the_table_of_commands(self):
        text = self.read("README.md")
        for name, (_, hint, description) in texts.COMMANDS.items():
            shown = " `%s`" % hint if hint else ""
            self.assertIn("| `/%s` |%s | %s |" % (name, shown, description), text)

    def test_gitignore_holds_the_lines_of_the_design(self):
        self.assertEqual(self.read("gitignore.txt"),
                         ".claude/learning/config.json\n.claude/learning/local/\n"
                         ".claude/learning/rehearsal/\n.claude/learning/rehearsal-reports/\n")

    def test_claude_md_section_has_every_superpowers_rule(self):
        text = self.read("claude-md-section.md")
        design = (ROOT / "docs" / "design.md").read_text(encoding="utf-8")
        table = design.split("## With Superpowers")[1].split("\n## ")[0]
        skills = re.findall(r"`([a-z]+(?:-[a-z]+)+)`", "\n".join(re.findall(r"(?m)^\| (.*?) \|", table)))
        self.assertIn("writing-plans", skills)
        for skill in skills:
            self.assertIn(skill, text)
        self.assertIn("TODO(owner", text)
        self.assertLessEqual(len(text.splitlines()), 40)


class SetupPromptTests(unittest.TestCase):
    def test_the_hooks_leave_setup_to_the_skill(self):
        with tempfile.TemporaryDirectory() as tmp:
            helpers.make_project(tmp)
            for prompt in ("/setup-learning", "/guided-learning:setup-learning"):
                self.assertIsNone(hooks.handle("UserPromptSubmit", {"prompt": prompt}, tmp))


if __name__ == "__main__":
    unittest.main()


class FieldTests(unittest.TestCase):
    """The field of the project, its words and the tuning switch, in what the AI reads."""

    def test_setup_asks_for_the_new_settings(self):
        text = read("setup-learning")
        for key in ("domain", "words", "tuning"):
            self.assertRegex(text, r"(?m)^   \| `%s` \|" % key)
        example = json.loads(re.search(r"```json\n(.*?)```", text, re.S).group(1))
        self.assertEqual(set(example) & {"domain", "words", "tuning"}, {"domain", "words", "tuning"})

    def test_skills_say_project_not_game(self):
        places = [SKILLS / d / "SKILL.md" for d in sorted(p.name for p in SKILLS.iterdir())]
        places += [ROOT / "templates" / "README.md", ROOT / "templates" / "claude-md-section.md"]
        for path in places:
            for line in path.read_bytes().decode("utf-8").splitlines():
                if re.search(r"\bgames?\b", line, re.I) and '"game"' not in line:
                    self.fail("%s: %s" % (path.name, line))

    def test_start_phase_targets_follow_tuning(self):
        self.assertIn("only when `tuning` in `project.json` is not false", read("start-phase"))

    def test_summarize_skips_tuning_without_targets(self):
        self.assertIn("If the plan has no targets, there is no tuning: go from the build to the wrap-up.",
                      read("summarize-phase"))

    def test_skills_use_the_words_of_the_project(self):
        for name in ("start-phase", "build-phase", "summarize-phase"):
            self.assertIn("`domain` and `words` of `.claude/learning/project.json`", read(name), name)
