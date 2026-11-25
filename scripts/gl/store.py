"""JSON files: tolerant reading, atomic writing, and a lock for read-modify-write."""
import hashlib
import json
import os
import tempfile
import time
import uuid

from . import texts

STALE_SECONDS = 10.0
LOCK_TIMEOUT = 15.0   # longer than STALE_SECONDS, so a dead holder is always taken over in time
_RETRY_PAUSE = 0.01


class BadJson(Exception):
    """A file is not valid JSON, or not an object. Carries `file` and `line`."""

    def __init__(self, file, line, message):
        super().__init__(message)
        self.file = str(file)
        self.line = line


class LockTimeout(Exception):
    pass


def _retry_permission(action, seconds=2.0):
    """Windows raises PermissionError while another process has the file open; retry briefly."""
    end = time.monotonic() + seconds
    while True:
        try:
            return action()
        except PermissionError:
            if time.monotonic() >= end:
                raise
            time.sleep(_RETRY_PAUSE)


def read(path):
    """Return the JSON object in path. A missing file reads as {}.

    A BOM and CRLF are accepted. Raises BadJson (with file and line) for invalid JSON
    or for JSON that is not an object.
    """
    def load():
        with open(path, "r", encoding="utf-8-sig", newline=None) as f:
            return f.read()

    try:
        text = _retry_permission(load)
    except FileNotFoundError:
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise BadJson(path, e.lineno, texts.bad_json(path, e.lineno, e.msg))
    if not isinstance(data, dict):
        raise BadJson(path, 1, texts.not_an_object(path))
    return data


def write(path, data):
    """Write data as JSON (UTF-8, LF) through a temporary file and os.replace.

    Creates parent folders. On failure the old file is untouched and no temporary file stays.
    """
    path = os.fspath(path)
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"  # may raise before any file exists
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=folder)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(text.encode("utf-8"))
        _retry_permission(lambda: os.replace(tmp, path))
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def file_hash(path):
    """sha256 hex of the file content with CRLF turned into LF."""
    with open(path, "rb") as f:
        data = f.read().replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def _age(path):
    try:
        return time.time() - os.stat(path).st_mtime
    except OSError:
        return None


def _take_over_stale(lock):
    """Remove a stale lock without ever deleting a fresh one made meanwhile.

    The lock is first renamed to a private name (atomic, one winner). Only then is its age
    checked again; if it turns out to be fresh (another process replaced it between our
    look and the rename), it is put back.
    """
    mine = "%s.stale-%s" % (lock, uuid.uuid4().hex)
    try:
        os.rename(lock, mine)
    except OSError:
        return
    age = _age(mine)
    if age is not None and age < STALE_SECONDS:
        try:
            os.link(mine, lock)   # fails if somebody created a new lock: then we leave it
        except OSError:
            pass
    try:
        os.remove(mine)
    except OSError:
        pass


def _acquire(lock, timeout):
    end = time.monotonic() + timeout
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            return
        except (FileExistsError, PermissionError):
            age = _age(lock)
            if age is not None and age >= STALE_SECONDS:
                _take_over_stale(lock)
                continue
        if time.monotonic() >= end:
            raise LockTimeout(texts.lock_timeout(lock[:-5]))
        time.sleep(_RETRY_PAUSE)


def _release(lock):
    try:
        _retry_permission(lambda: os.remove(lock))
    except FileNotFoundError:
        pass


def update(path, fn, timeout=LOCK_TIMEOUT):
    """Read path under `<path>.lock`, call fn(data), write the result, return it.

    fn may change data in place (and return None) or return a new dict.
    """
    path = os.fspath(path)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    lock = path + ".lock"
    _acquire(lock, timeout)
    try:
        data = read(path)
        result = fn(data)
        if result is not None:
            data = result
        write(path, data)
        return data
    finally:
        _release(lock)
