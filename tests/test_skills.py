import json
import re
import tempfile
import unittest
from pathlib import Path

import helpers
from gl import hooks, log, texts

ROOT = Path(__file__).resolve().parent.parent
SKILLS = ROOT / "skills"
WITH_STATUS = ("build-phase", "summarize-phase")
STATUS_LINE = '!`bash "${CLAUDE_PLUGIN_ROOT}/scripts/run.sh" status $ARGUMENTS`'
RUN = 'bash "${CLAUDE_PLUGIN_ROOT}/scripts/run.sh" '


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


class SkillTests(unittest.TestCase):
    def each(self):
        for name in texts.COMMANDS:
            with self.subTest(name):
                yield name, read(name)

    def test_one_skill_per_command(self):
        self.assertEqual({p.parent.name for p in SKILLS.glob("*/SKILL.md")}, set(texts.COMMANDS))

    def test_descriptions_and_hints_match(self):
        for name, text in self.each():
            head = frontmatter(text)
            _, hint, description = texts.COMMANDS[name]
            self.assertEqual(head["name"], name)
            self.assertEqual(head["description"], description)
            self.assertEqual(head.get("argument-hint", ""), hint)
            self.assertEqual("argument-hint" in head, bool(hint))

    def test_hints_are_text_and_no_yaml_list(self):
        for name, text in self.each():
            for line in re.findall(r"(?m)^(?:description|argument-hint): .*$", text):
                self.assertRegex(line, r'^[a-z-]+: ".*"$')

    def test_all_are_owner_only(self):
        for name, text in self.each():
            self.assertEqual(frontmatter(text).get("disable-model-invocation"), "true")

    def test_at_most_80_lines_and_lf(self):
        for name, text in self.each():
            self.assertLessEqual(len(text.splitlines()), 80)
            self.assertNotIn("\r", text)

    def test_status_is_inserted_where_the_phase_goes_on(self):
        for name, text in self.each():
            self.assertEqual(text.split("\n").count(STATUS_LINE), int(name in WITH_STATUS))
            self.assertEqual(text.count("!`"), int(name in WITH_STATUS))
            allowed = frontmatter(text).get("allowed-tools", "")
            self.assertEqual("Bash(bash *run.sh* status*)" in allowed, name in WITH_STATUS)

    def test_a_missing_project_names_setup(self):
        for name, text in self.each():
            if name != "setup-learning":
                self.assertIn("/setup-learning", text)

    def test_script_calls_exist(self):
        for name, text in self.each():
            for call in re.findall(re.escape(RUN) + r"([a-z-]+)", text):
                self.assertIn(call, {"status", "log", "record-tests", "hand-over", "setup"})

    def test_records_have_the_fields_of_the_log(self):
        kinds = set()
        for name, text in self.each():
            for kind, fields in re.findall(r"\blog ([a-z]+) ([a-z]+=[^`\n]*)`", text):
                names = [f for f in re.findall(r"\b([a-z]+)=", fields) if f != "phase"]
                self.assertEqual(tuple(names), log.FIELDS[kind], kind)
                kinds.add(kind)
        self.assertEqual(kinds, set(log.FIELDS) - {"note"})   # notes go to phase-N.md

    def test_commands_named_exist(self):
        for name, text in self.each():
            for command in re.findall(r"(?<![\w/])/([a-z]+-(?:phase|learning))\b", text):
                self.assertIn(command, texts.COMMANDS)


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
