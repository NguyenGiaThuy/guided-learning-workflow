"""Start a program so that it and all its children can be stopped, also those left after a normal exit.

Windows: a job object. Elsewhere: a process group of its own; a child that leaves the group is not found.
"""
import os
import signal
import subprocess
import sys

WAIT = 10   # seconds for a stopped program to end


def _note(text):
    print("Note: " + text, file=sys.stderr, flush=True)


# --- the job object of Windows -----------------------------------------------------------------------------

if os.name == "nt":
    import ctypes
    from ctypes import wintypes

    _SUSPENDED = 0x4             # CREATE_SUSPENDED: no child can start before the program is in the job
    _KILL_ON_CLOSE = 0x2000      # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE: also if this script itself is killed
    _EXTENDED_LIMITS = 9         # JobObjectExtendedLimitInformation

    class _Basic(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class _Limits(ctypes.Structure):
        _fields_ = [("Basic", _Basic), ("IoInfo", ctypes.c_uint64 * 6), ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t)]

    _kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel.CreateJobObjectW.restype = wintypes.HANDLE
    _kernel.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    _kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
    _kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _kernel.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    _ntdll = ctypes.WinDLL("ntdll")
    _ntdll.NtResumeProcess.argtypes = [wintypes.HANDLE]


def _new_job():
    """A job that ends with this script; None if Windows does not give one."""
    job = _kernel.CreateJobObjectW(None, None)
    if not job:
        return None
    limits = _Limits()
    limits.Basic.LimitFlags = _KILL_ON_CLOSE
    if not _kernel.SetInformationJobObject(job, _EXTENDED_LIMITS, ctypes.byref(limits), ctypes.sizeof(limits)):
        _kernel.CloseHandle(job)
        return None
    return job


# --- start and stop ----------------------------------------------------------------------------------------

class Program:
    """A started program. stop() ends it and its children, and must be called in every case."""

    def __init__(self, command, **options):
        self._job = None
        if os.name != "nt":
            self.process = subprocess.Popen(command, start_new_session=True, **options)
            return
        self.process = subprocess.Popen(command, creationflags=_SUSPENDED, **options)
        try:
            handle = int(self.process._handle)
            self._job = _new_job()
            if self._job and not _kernel.AssignProcessToJobObject(self._job, handle):
                _kernel.CloseHandle(self._job)
                self._job = None
            if not self._job:
                _note("no job object, so children may outlive the program %d" % self.process.pid)
            _ntdll.NtResumeProcess(handle)
        except BaseException:
            self.stop()
            raise

    def stop(self):
        if os.name != "nt":
            try:
                os.killpg(self.process.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):   # all ended; macOS says the second for a zombie
                pass
        elif self._job:
            _kernel.TerminateJobObject(self._job, 1)
            _kernel.CloseHandle(self._job)
            self._job = None
        elif self.process.poll() is None:
            try:
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(self.process.pid)], capture_output=True,
                               timeout=WAIT)
            except (OSError, subprocess.TimeoutExpired):
                pass   # reap() tries another way
        reap(self.process, WAIT)
        if self.process.stdin and not self.process.stdin.closed:
            try:
                self.process.stdin.close()
            except OSError:
                pass


def reap(process, seconds):
    """Wait for a stopped program. One that does not end is killed once more, and noted if that does not help."""
    try:
        process.wait(seconds)
        return
    except subprocess.TimeoutExpired:
        process.kill()
    try:
        process.wait(seconds)
    except subprocess.TimeoutExpired:
        _note("the program %d does not end" % process.pid)
