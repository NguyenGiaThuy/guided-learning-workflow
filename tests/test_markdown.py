import shutil
import tempfile
import unittest
from pathlib import Path

import helpers  # noqa: F401  (puts scripts/ on the path)
from gl import markdown

FULL = """# Phase 2

## Notes for later
something

## Answers

### q1
<!-- the owner's words -->
It takes the nearest one.

### q2
...

## Concept summary
### Enemy AI
A state machine.

## Lessons
- one
- two
  - a detail of two
- three
-

## Process
Surprised me: the tests
Differently: start smaller
"""


class MarkdownTests(unittest.TestCase):
    def load(self, text):
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, folder, True)
        path = folder / "phase-2.md"
        path.write_bytes(text if isinstance(text, bytes) else text.encode("utf-8"))
        return markdown.load(path)

    def check_full(self, md):
        self.assertTrue(md.answer("q1"))
        self.assertFalse(md.answer("q2"))
        self.assertFalse(md.answer("q3"))
        self.assertTrue(md.summary("Enemy AI"))
        self.assertEqual(md.lessons, ["one", "two", "three"])
        self.assertEqual((md.surprised, md.differently), ("the tests", "start smaller"))

    def test_all_sections(self):
        self.check_full(self.load(FULL))

    def test_bom_and_crlf(self):
        self.check_full(self.load(b"\xef\xbb\xbf" + FULL.replace("\n", "\r\n").encode("utf-8")))

    def test_headings_ignore_case_and_spaces(self):
        self.check_full(self.load(FULL.replace("## Answers", "##   ANSWERS  ").replace("### q1", "###  Q1 ")
                                  .replace("### Enemy AI", "### enemy ai ##").replace("## Process", "## process")))

    def test_missing_file_is_empty(self):
        md = markdown.load(Path(tempfile.gettempdir()) / "no-such-folder" / "phase-9.md")
        self.assertEqual((md.answer("q1"), md.lessons, md.surprised, md.differently), ("", [], "", ""))

    def test_comments_and_placeholders_are_not_text(self):
        md = self.load("## Answers\n### q1\n<!-- a\nb -->\n### q2\n<your answer>\n### q3\n- \n1.\n### q4\n42\n"
                       "## Lessons\n- <lesson>\n- ...\n1. real\n## Process\n- **Surprised me:** <!-- x -->\n"
                       "Differently:\n")
        self.assertEqual([bool(md.answer(q)) for q in ("q1", "q2", "q3", "q4")], [False, False, False, True])
        self.assertEqual(md.lessons, ["real"])
        self.assertEqual((md.surprised, md.differently), ("", ""))

    def test_process_takes_bold_bullets_and_following_lines(self):
        md = self.load("## Process\n- **Surprised me:** a\n  b\n- *Differently*: c\n")
        self.assertEqual((md.surprised, md.differently), ("a b", "c"))

    def test_a_heading_inside_a_code_fence_is_text(self):
        md = self.load("## Answers\n### q1\n```\n## Lessons\n- x\n```\n")
        self.assertIn("## Lessons", md.answer("q1"))
        self.assertEqual(md.lessons, [])

    def test_same_heading_in_another_section_does_not_count(self):
        md = self.load("## Notes for later\n### q1\ntext\n### Enemy AI\ntext\n")
        self.assertFalse(md.answer("q1") or md.summary("Enemy AI"))


if __name__ == "__main__":
    unittest.main()
