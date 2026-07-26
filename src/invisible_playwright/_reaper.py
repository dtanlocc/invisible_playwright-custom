"""Reap this session's browser tree, and nothing else.

THE BUG THIS EXISTS FOR
-----------------------
After twelve runs of one test - three of which timed out - eleven ``firefox``
processes were still alive, every one of them parented to a run that had
already exited. The launcher closed with ``browser.close()`` and trusted
Playwright's teardown, and on Windows that is not enough: ``firefox.exe`` is a
launcher stub that spawns the real browser as a child and then EXITS. The real
browser is re-parented away, so whoever was holding the stub is now holding
nothing. Any path where teardown does not complete - a timeout, an exception
out of the ``with`` block, a killed runner - leaves the tree behind, holding
memory and a profile directory, once per session.

WHY A TOKEN AND NOT A SEARCH
----------------------------
The sibling product finds its browser by matching the ``-profile`` directory on
the command line. That works there because it owns the profile path. This
package does not: in the ordinary launch mode Playwright creates the profile
itself and never tells us where. Everything else available for matching -
"a firefox that appeared after we started", "a firefox running our binary" - is
a HEURISTIC, and the failure it invites is the one failure a reaper must never
have: on a fleet, several sessions start within the same second on the same
binary, and a wrong guess kills a healthy browser belonging to someone else.

So each session mints a random token and puts it in the browser's environment.
Child processes inherit the environment, so every content process carries it
too, and a process either has this session's token or it does not - there is
nothing to guess and nothing to race. Verified on Windows, where the launcher
stub made this necessary in the first place: ``psutil.Process.environ()`` reads
a same-user process's block, and children show the inherited value.

The rule this module holds to: kill on POSITIVE identification only. A process
whose environment cannot be read is left alone. Leaking a browser is a bug;
killing someone else's is an incident, and only one of the two is recoverable.
"""
from __future__ import annotations

import os
import secrets
import time
from typing import Any, List

# Named in the environment of every process in the tree. Read back through
# psutil; never read by the browser itself.
TOKEN_VAR = "INVPW_SESSION_TOKEN"

try:  # psutil is a declared dependency; guarded so an import problem in a
    # user's environment degrades to a loud no-op rather than breaking launch.
    import psutil
except Exception:  # pragma: no cover - exercised by test_reaper's monkeypatch
    psutil = None  # type: ignore[assignment]


def new_token() -> str:
    """A token for one session. Random, so two sessions never collide."""
    return secrets.token_hex(16)


def _carries(proc: Any, token: str) -> bool:
    """True only when we can READ the environment and it holds our token.

    Every failure answers False. A process we cannot inspect is a process we do
    not touch - see the module docstring.
    """
    try:
        return proc.environ().get(TOKEN_VAR) == token
    except Exception:
        return False


def find_session_processes(token: str) -> List[Any]:
    """Every live process carrying ``token``, deepest child first.

    Deepest-first so that terminating in order takes the content processes
    before the parent that would otherwise restart or orphan them.
    """
    if psutil is None or not token:
        return []
    found = []
    for proc in psutil.process_iter(["pid", "ppid"]):
        if _carries(proc, token):
            found.append(proc)
    by_pid = {p.pid for p in found}
    # A child's parent being in the set is what "deeper" means here; no tree
    # walk is needed because the token already delimits the tree exactly.
    found.sort(key=lambda p: (p.info.get("ppid") in by_pid), reverse=True)
    return found


def reap(token: str, *, timeout: float = 5.0) -> int:
    """Terminate everything carrying ``token``. Returns how many were killed.

    Graceful ``terminate()`` first so the browser can flush and remove its
    profile directory, then ``kill()`` for whatever is still standing. Returns
    a count rather than nothing so a caller - or a test - can tell the
    difference between "nothing was leaked" and "the reaper did not run", which
    are the two outcomes that look identical from the outside.
    """
    procs = find_session_processes(token)
    if not procs:
        return 0
    for proc in procs:
        try:
            proc.terminate()
        except Exception:
            pass
    gone, alive = [], procs
    try:
        gone, alive = psutil.wait_procs(procs, timeout=timeout)
    except Exception:
        pass
    for proc in alive:
        try:
            proc.kill()
        except Exception:
            pass
    if alive:
        try:
            psutil.wait_procs(alive, timeout=1.0)
        except Exception:
            pass
    return len(procs)


def stamp(env: dict, token: str) -> dict:
    """Put ``token`` into a copy of ``env`` for the browser to inherit."""
    out = dict(env)
    out[TOKEN_VAR] = token
    return out


# ── the path no in-process cleanup can reach ──────────────────────────────
#
# MEASURED, because the first version of this file fixed the wrong path. An
# exception thrown inside the ``with`` block does NOT leak: ``__exit__`` runs,
# Playwright tears down, and an interleaved A/B over four launches found zero
# survivors with the reaper disabled. The bug report's other detail was the
# real one - three of the twelve runs had TIMED OUT. When the runner is killed,
# ``__exit__`` never executes, and no amount of care inside ``_teardown`` can
# help. Reproduced directly: launch, SIGKILL the runner, count. Eight survivors
# on the first attempt, twelve on the second.
#
# So the guarantee has to come from the operating system rather than from our
# own code running at the right moment. A Windows job object with
# KILL_ON_JOB_CLOSE does exactly that: this process holds the only handle, and
# when it dies - cleanly, by exception, or killed outright - the kernel closes
# the handle and terminates everything in the job. Processes created by a
# process already in a job join it automatically, so content processes the
# browser spawns later are covered without being tracked.
#
# Windows only, and that matches where the bug is. On Linux the launched
# process IS the browser and Playwright keeps hold of it; the stub that spawns
# the real browser and exits, re-parenting the tree out of everyone's reach, is
# a Windows thing.

_JOB_HANDLE: Any = None  # module-level: it must outlive any one session object

_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_PROCESS_SET_QUOTA = 0x0100
_PROCESS_TERMINATE = 0x0001


def _create_kill_on_close_job() -> Any:
    """A job object whose closure kills its members. None if unavailable."""
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class _IO_COUNTERS(ctypes.Structure):
        _fields_ = [(n, ctypes.c_ulonglong) for n in
                    ("ReadOperationCount", "WriteOperationCount",
                     "OtherOperationCount", "ReadTransferCount",
                     "WriteTransferCount", "OtherTransferCount")]

    class _BASIC_LIMIT(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.POINTER(ctypes.c_ulong)),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _EXTENDED_LIMIT(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _BASIC_LIMIT),
            ("IoInfo", _IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        return None
    info = _EXTENDED_LIMIT()
    info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    ok = kernel32.SetInformationJobObject(
        job, _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
        ctypes.byref(info), ctypes.sizeof(info),
    )
    if not ok:
        kernel32.CloseHandle(job)
        return None
    return job


def bind_tree_to_this_process(token: str, *, wait: float = 10.0) -> int:
    """Tie every process carrying ``token`` to this process's lifetime.

    Returns how many were bound. 0 means the guarantee is NOT in place - on a
    non-Windows host, where it is not needed, and on a failure, where the
    caller should not be told otherwise.

    Waits for the tree to appear because the browser is spawned asynchronously
    by the driver; the token makes that wait exact rather than a guess about
    how long a launch takes.
    """
    global _JOB_HANDLE
    if os.name != "nt" or psutil is None or not token:
        return 0
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    if _JOB_HANDLE is None:
        _JOB_HANDLE = _create_kill_on_close_job()
        if not _JOB_HANDLE:
            return 0

    deadline = time.monotonic() + wait
    bound = 0
    seen: set = set()
    while time.monotonic() < deadline:
        procs = find_session_processes(token)
        for proc in procs:
            if proc.pid in seen:
                continue
            handle = kernel32.OpenProcess(
                _PROCESS_SET_QUOTA | _PROCESS_TERMINATE, False, proc.pid
            )
            if not handle:
                continue
            try:
                if kernel32.AssignProcessToJobObject(_JOB_HANDLE, handle):
                    bound += 1
                seen.add(proc.pid)
            finally:
                kernel32.CloseHandle(handle)
        if bound:
            break
        time.sleep(0.25)
    return bound


def token_from_environ() -> str:
    """The token this process was itself launched with, if any.

    Only used by tests and by the diagnostic path; a browser never reads it.
    """
    return os.environ.get(TOKEN_VAR, "")


def wait_until_gone(token: str, timeout: float = 10.0) -> bool:
    """True once nothing carries ``token`` any more, False on timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not find_session_processes(token):
            return True
        time.sleep(0.2)
    return not find_session_processes(token)
