import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from gl import version  # noqa: E402


class HashTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "scripts").mkdir()
        (self.tmp / "scripts" / "a.py").write_bytes(b"x = 1\ny = 2\n")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_hash_is_stable(self):
        self.assertEqual(version.plugin_hash(self.tmp), version.plugin_hash(self.tmp))
        self.assertRegex(version.plugin_hash(), r"^[0-9a-f]{6}$")

    def test_hash_ignores_line_endings_and_pycache(self):
        before = version.plugin_hash(self.tmp)
        (self.tmp / "scripts" / "a.py").write_bytes(b"x = 1\r\ny = 2\r\n")
        cache = self.tmp / "scripts" / "__pycache__"
        cache.mkdir()
        (cache / "a.pyc").write_bytes(b"junk")
        self.assertEqual(before, version.plugin_hash(self.tmp))

    def test_hash_changes_with_content(self):
        before = version.plugin_hash(self.tmp)
        (self.tmp / "scripts" / "a.py").write_bytes(b"x = 2\ny = 2\n")
        self.assertNotEqual(before, version.plugin_hash(self.tmp))

    def test_version_read_from_plugin_json(self):
        self.assertEqual(version.VERSION, "0.1.0")


class RunShTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("bash"), "bash not available")
    def test_run_sh_prints_version(self):
        out = subprocess.run(
            ["bash", "scripts/run.sh", "version"], cwd=ROOT,
            capture_output=True, text=True, encoding="utf-8", timeout=60,
        )
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertRegex(out.stdout.strip(), r"^0\.1\.0 [0-9a-f]{6}$")


if __name__ == "__main__":
    unittest.main()
