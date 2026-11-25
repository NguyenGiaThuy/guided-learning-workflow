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

    def run_sh(self, **stubs):
        """run.sh version with stubs for python and python3, which are first in the path."""
        bash = shutil.which("bash")
        with tempfile.TemporaryDirectory() as tmp:
            for name, body in stubs.items():
                path = Path(tmp) / name
                path.write_bytes(("#!/bin/sh\n%s\n" % body).encode("utf-8"))
                path.chmod(0o755)
            env = dict(os.environ, PATH=tmp + os.pathsep + os.environ["PATH"])
            return subprocess.run([bash, "scripts/run.sh", "version"], cwd=ROOT, env=env, capture_output=True,
                                  text=True, encoding="utf-8", timeout=60)

    # An interpreter that runs, but is older than 3.9, and the real one.
    OLD = 'case "$2" in "") exit 0;; *) echo too old; exit 1;; esac'
    REAL = 'echo real >&2; exec "%s" "$@"' % Path(sys.executable).as_posix()

    @unittest.skipUnless(shutil.which("bash"), "bash not available")
    def test_run_sh_takes_the_first_python_that_is_new_enough(self):
        for stubs, real in (({"python": self.OLD, "python3": self.REAL}, "real"),
                            ({"python": "exit 1", "python3": self.REAL}, "real"),
                            ({"python": self.REAL, "python3": self.OLD}, "real")):
            out = self.run_sh(**stubs)
            self.assertEqual(out.returncode, 0, out)
            self.assertRegex(out.stdout.strip(), r"^0\.1\.0 [0-9a-f]{6}$")
            self.assertIn(real, out.stderr)

    @unittest.skipUnless(shutil.which("bash"), "bash not available")
    def test_run_sh_says_what_is_missing(self):
        out = self.run_sh(python=self.OLD, python3="exit 1")
        self.assertEqual((out.returncode, out.stdout), (127, ""))
        self.assertIn("guided-learning", out.stderr)
        self.assertIn("Python 3.9 or newer", out.stderr)


if __name__ == "__main__":
    unittest.main()
