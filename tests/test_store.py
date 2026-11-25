import os
import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import helpers  # noqa: F401  (sets sys.path)
from gl import store


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_missing_file_reads_as_empty_dict(self):
        self.assertEqual(store.read(self.tmp / "nope.json"), {})

    def test_write_then_read_creates_folders_and_uses_lf(self):
        p = self.tmp / "a" / "b.json"
        store.write(p, {"x": "é"})
        self.assertEqual(store.read(p), {"x": "é"})
        self.assertNotIn(b"\r", p.read_bytes())
        self.assertEqual([f.name for f in p.parent.iterdir()], ["b.json"])

    def test_bom_and_crlf_are_read(self):
        p = self.tmp / "c.json"
        p.write_bytes(b'\xef\xbb\xbf{\r\n  "a": 1\r\n}\r\n')
        self.assertEqual(store.read(p), {"a": 1})

    def test_bad_json_names_file_and_line(self):
        p = self.tmp / "bad.json"
        p.write_text('{\n  "a": 1,\n  "b": \n', encoding="utf-8")
        with self.assertRaises(store.BadJson) as cm:
            store.read(p)
        e = cm.exception
        self.assertEqual(Path(e.file), p)
        self.assertEqual(e.line, 4)
        self.assertIn("bad.json", str(e))
        self.assertIn("4", str(e))

    def test_not_an_object_is_bad_json(self):
        p = self.tmp / "list.json"
        p.write_text("[1]", encoding="utf-8")
        with self.assertRaises(store.BadJson):
            store.read(p)

    def test_failed_write_leaves_no_partial_file(self):
        p = self.tmp / "d.json"
        store.write(p, {"ok": 1})
        with self.assertRaises(TypeError):
            store.write(p, {"bad": object()})
        self.assertEqual(store.read(p), {"ok": 1})
        self.assertEqual([f.name for f in self.tmp.iterdir()], ["d.json"])

    def test_file_hash_ignores_crlf(self):
        a, b = self.tmp / "a.txt", self.tmp / "b.txt"
        a.write_bytes(b"one\ntwo\n")
        b.write_bytes(b"one\r\ntwo\r\n")
        self.assertEqual(store.file_hash(a), store.file_hash(b))
        self.assertRegex(store.file_hash(a), r"^[0-9a-f]{64}$")

    def test_two_updates_at_once_keep_both(self):
        p = self.tmp / "log.json"
        errors = []

        def add(i):
            try:
                def fn(d):
                    d.setdefault("log", []).append(i)
                    return d
                store.update(p, fn)
            except Exception as e:  # pragma: no cover
                errors.append(e)

        threads = [threading.Thread(target=add, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(sorted(store.read(p)["log"]), list(range(20)))
        self.assertFalse(Path(str(p) + ".lock").exists())

    def test_update_removes_lock_when_fn_raises(self):
        p = self.tmp / "e.json"

        def boom(d):
            raise ValueError("x")

        with self.assertRaises(ValueError):
            store.update(p, boom)
        self.assertFalse(Path(str(p) + ".lock").exists())

    def test_update_may_mutate_in_place(self):
        p = self.tmp / "f.json"
        out = store.update(p, lambda d: d.update(n=1))
        self.assertEqual(out, {"n": 1})
        self.assertEqual(store.read(p), {"n": 1})

    def test_stale_lock_is_taken_over(self):
        p = self.tmp / "g.json"
        lock = Path(str(p) + ".lock")
        lock.write_text("old")
        old = time.time() - 20
        os.utime(lock, (old, old))
        store.update(p, lambda d: {"done": True})
        self.assertEqual(store.read(p), {"done": True})
        self.assertFalse(lock.exists())

    def test_fresh_lock_times_out_and_is_left_alone(self):
        p = self.tmp / "h.json"
        lock = Path(str(p) + ".lock")
        lock.write_text("busy")
        with self.assertRaises(store.LockTimeout):
            store.update(p, lambda d: d, timeout=0.3)
        self.assertTrue(lock.exists())

    def test_slow_holder_does_not_lose_the_other_update(self):
        p = self.tmp / "slow.json"
        calls = []

        def slow(d):
            calls.append(1)
            if len(calls) == 1:
                time.sleep(0.9)   # longer than the (lowered) stale age: B takes the lock over
            d["A"] = 1

        with mock.patch.object(store, "STALE_SECONDS", 0.3):
            a = threading.Thread(target=lambda: store.update(p, slow))
            a.start()
            time.sleep(0.5)
            store.update(p, lambda d: d.update(B=1))
            a.join()
        self.assertEqual(store.read(p), {"A": 1, "B": 1})
        self.assertEqual(len(calls), 2)   # A re-ran fn on the re-read data
        self.assertFalse(Path(str(p) + ".lock").exists())

    def test_unremovable_stale_lock_still_times_out(self):
        p = self.tmp / "stuck.json"
        lock = Path(str(p) + ".lock")
        lock.write_text("old")
        old = time.time() - 20
        os.utime(lock, (old, old))
        real_rename = os.rename

        def refuse(src, dst):
            if os.fspath(src) == str(lock):
                raise PermissionError("open elsewhere")
            return real_rename(src, dst)

        start = time.monotonic()
        with mock.patch.object(os, "rename", refuse):
            with self.assertRaises(store.LockTimeout):
                store.update(p, lambda d: d, timeout=0.5)
        self.assertLess(time.monotonic() - start, 3)

    def test_undecodable_file_is_bad_json_with_file_and_line(self):
        for name, raw in (("u16.json", '{"a": 1}'.encode("utf-16")),
                          ("bad.json", b'{\n"a": \xff}')):
            p = self.tmp / name
            p.write_bytes(raw)
            with self.assertRaises(store.BadJson) as cm:
                store.read(p)
            self.assertIn(name, str(cm.exception))
            self.assertGreaterEqual(cm.exception.line, 1)


if __name__ == "__main__":
    unittest.main()
