"""JSON files: tolerant reading, atomic writing, and a lock for read-modify-write."""
import hashlib
import json
import os
import time
import uuid
from datetime import datetime

from . import texts

STALE_SECONDS = 10.0
LOCK_TIMEOUT = 15.0   # longer than STALE_SECONDS, so a dead holder is always taken over in time
_RETRY_PAUSE = 0.01
MAX_ATTEMPTS = 5


class BadJson(Exception):
    """A file is not valid JSON, or not an object. Carries `file` and `line`."""

    def __init__(self, file, line, message):
        super().__init__(message)
        self.file = str(file)
        self.line = line


class LockTimeout(Exception):
    pass


def now():
    """The time of a record, with the offset of this machine."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def retry_permission(action, seconds=2.0):
    """Windows raises PermissionError while another process has the file open; retry briefly."""
    end = time.monotonic() + seconds
    while True:
        try:
            return action()
        except PermissionError:
            if time.monotonic() >= end:
                raise
            time.sleep(_RETRY_PAUSE)


def read_bytes(path):
    """The content of a file that another process may have open for a moment."""
    def load():
        with open(path, "rb") as f:
            return f.read()

    return retry_permission(load)


def read(path):
    """Return the JSON object in path. A missing file reads as {}.

    A BOM and CRLF are accepted. Raises BadJson (with file and line) for invalid JSON
    for text that is not UTF-8, or for JSON that is not an object.
    """
    try:
        raw = read_bytes(path)
    except FileNotFoundError:
        return {}
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        line = raw.count(b"\n", 0, e.start) + 1
        raise BadJson(path, line, texts.bad_encoding(path, line))
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise BadJson(path, e.lineno, texts.bad_json(path, e.lineno, e.msg))
    if not isinstance(data, dict):
        raise BadJson(path, 1, texts.not_an_object(path))
    return data


def write(path, data):
    """Write data as JSON, like write_text."""
    write_text(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def _new_file(folder):
    """(descriptor, path) of a new temporary file with the usual mode.

    Not tempfile.mkstemp: in a folder without permission it tries for minutes on Windows, and the
    file that stays would be readable only for the user who wrote it.
    """
    path = os.path.join(folder, ".tmp-" + uuid.uuid4().hex)
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0)
    return retry_permission(lambda: os.open(path, flags, 0o666)), path


def write_text(path, text):
    """Write text (UTF-8, LF) through a temporary file and os.replace.

    Creates parent folders. On failure the old file is untouched and no temporary file stays.
    """
    path = os.fspath(path)
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    fd, tmp = _new_file(folder)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(text.encode("utf-8"))
        retry_permission(lambda: os.replace(tmp, path))
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def file_hash(path):
    """sha256 hex of the file content with CRLF turned into LF."""
    return hashlib.sha256(read_bytes(path).replace(b"\r\n", b"\n")).hexdigest()


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
        return False
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
    return True


def _acquire(lock, timeout):
    """Create the lock file holding a unique token; return the token."""
    token = uuid.uuid4().hex
    end = time.monotonic() + timeout
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            try:
                os.write(fd, token.encode("ascii"))
            finally:
                os.close(fd)
            return token
        except (FileExistsError, PermissionError):
            age = _age(lock)
            if age is not None and age >= STALE_SECONDS and _take_over_stale(lock):
                continue
        if time.monotonic() >= end:
            raise LockTimeout(texts.lock_timeout(lock[:-5]))
        time.sleep(_RETRY_PAUSE)


def _owns(lock, token):
    try:
        with open(lock, "rb") as f:
            return f.read().decode("ascii", "replace") == token
    except OSError:
        return False


def _release(lock, token):
    """Remove the lock only if it is still ours (it may have been taken over)."""
    if not _owns(lock, token):
        return
    try:
        retry_permission(lambda: os.remove(lock))
    except FileNotFoundError:
        pass


def update(path, fn, timeout=LOCK_TIMEOUT, after=None):
    """Read path under `<path>.lock`, call fn(data), write the result, return it.

    after() is called once the file is written, while the lock is still held.
    fn may change data in place (and return None) or return a new dict.
    If the lock was taken over as stale while fn ran, nothing is written; the update is
    started again (fn runs again on freshly read data), at most MAX_ATTEMPTS times.
    """
    path = os.fspath(path)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    lock = path + ".lock"
    for _ in range(MAX_ATTEMPTS):
        token = _acquire(lock, timeout)
        try:
            data = read(path)
            result = fn(data)
            if result is not None:
                data = result
            if _owns(lock, token):
                write(path, data)
                if after:
                    after()
                return data
        finally:
            _release(lock, token)
    raise LockTimeout(texts.lock_timeout(path))
