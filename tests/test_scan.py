import os
import tempfile
import unittest
from pathlib import Path

from helpers import make_project
from gl import project, scan


class ScanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def write(self, name, data):
        p = self.root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
        return p

    def test_todos_in_order(self):
        p = self.write("a.cs", "// TODO(owner 1.2) b\n// TODO(owner 1.1) a\n// TODO(owner 2.1)\n")
        self.assertEqual(scan.todos(p), ["1.2", "1.1", "2.1"])

    def test_todo_in_any_comment_style(self):
        p = self.write("a.txt", "// TODO(owner 1.1)\n# TODO(owner 1.2)\n-- TODO(owner 1.3)\n")
        self.assertEqual(scan.todos(p), ["1.1", "1.2", "1.3"])

    def test_duplicates_once_missing_file_bom_crlf_bad_bytes(self):
        self.assertEqual(scan.todos(self.root / "none.cs"), [])
        p = self.write("a.cs", b"\xef\xbb\xbf// TODO(owner 1.1)\r\n// TODO(owner 1.1)\r\n\xff\xfe TODO(owner 3.4)")
        self.assertEqual(scan.todos(p), ["1.1", "3.4"])

    def test_removed_finds_only_lost_ones(self):
        before = "TODO(owner 1.1) TODO(owner 1.2) TODO(owner 1.3)"
        after = "TODO(owner 1.2)"
        self.assertEqual(scan.removed(before, after), ["1.1", "1.3"])
        self.assertEqual(scan.removed(after, before), [])

    def test_last_code_change_and_owner_marks(self):
        root = make_project(self.tmp.name + "/p")
        proj = project.find(root)
        self.assertEqual(scan.last_code_change(proj), 0.0)
        a = self.write("p/src/b/B.cs", 'x\n[Explicit("Owner")]\n')
        b = self.write("p/src/A.cs", '[Explicit("Owner")] [Explicit("Owner")]\n')
        self.write("p/src/readme.md", '[Explicit("Owner")]\n')
        os.utime(a, (1000, 1000))
        os.utime(b, (2000, 2000))
        self.assertEqual(scan.last_code_change(proj), 2000)
        self.assertEqual(scan.owner_marks(proj), ["src/A.cs:1", "src/b/B.cs:2"])


if __name__ == "__main__":
    unittest.main()
