"""The reaper: does it kill our tree, and does it leave everything else alone.

These use REAL processes rather than mocks. The bug being fixed is about what
the operating system does with a re-parented process tree, and a mock of
psutil would only ever confirm that the code calls the functions it calls -
which is not the thing in doubt. Short-lived `python -c "sleep"` children stand
in for the browser: what matters is that they carry an inherited environment
block, and they do.

The negative case is the important one. A reaper that kills everything passes
every positive test ever written.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

import pytest

from invisible_playwright import _reaper

pytestmark = pytest.mark.unit

psutil = pytest.importorskip("psutil")

# Long enough that nothing exits on its own during a test, short enough that a
# leaked child from a crashed run is gone before it bothers anyone.
_SLEEP = 30


def _spawn(token: str | None) -> subprocess.Popen:
    env = dict(os.environ)
    env.pop(_reaper.TOKEN_VAR, None)
    if token:
        env = _reaper.stamp(env, token)
    return subprocess.Popen(
        [sys.executable, "-c", f"import time; time.sleep({_SLEEP})"], env=env
    )


def _reap_all(*procs: subprocess.Popen) -> None:
    for p in procs:
        try:
            p.kill()
            p.wait(timeout=5)
        except Exception:
            pass


def test_a_token_is_unique_per_session():
    """Two sessions must never share a token, or one reaps the other."""
    assert len({_reaper.new_token() for _ in range(200)}) == 200


def test_it_finds_the_process_carrying_the_token():
    token = _reaper.new_token()
    proc = _spawn(token)
    try:
        time.sleep(0.6)
        found = {p.pid for p in _reaper.find_session_processes(token)}
        assert proc.pid in found
    finally:
        _reap_all(proc)


def test_a_child_inherits_the_token_and_is_reaped_with_the_parent():
    """The whole point on Windows: the tree, not the process we launched.

    A grandchild spawned by the marked process carries the same environment,
    so it is found and killed even though nothing ever recorded its pid.
    """
    token = _reaper.new_token()
    env = _reaper.stamp(dict(os.environ), token)
    parent = subprocess.Popen(
        [sys.executable, "-c",
         f"import subprocess,sys,time;"
         f"subprocess.Popen([sys.executable,'-c','import time; time.sleep({_SLEEP})']);"
         f"time.sleep({_SLEEP})"],
        env=env,
    )
    try:
        time.sleep(1.5)
        pids = {p.pid for p in _reaper.find_session_processes(token)}
        assert len(pids) >= 2, f"grandchild not found, only {pids}"
        killed = _reaper.reap(token)
        assert killed >= 2
        assert _reaper.wait_until_gone(token, timeout=8.0)
    finally:
        _reap_all(parent)


def test_it_does_not_touch_a_process_with_a_different_token():
    """The incident this design exists to prevent.

    Two sessions running side by side on the same binary. Reaping one must
    leave the other running - a leaked browser is a bug, killing someone
    else's is an incident, and only one of the two is recoverable.
    """
    mine, theirs = _reaper.new_token(), _reaper.new_token()
    a, b = _spawn(mine), _spawn(theirs)
    try:
        time.sleep(0.8)
        assert _reaper.reap(mine) >= 1
        assert _reaper.wait_until_gone(mine, timeout=8.0)
        assert b.poll() is None, "reaping one session killed the other's process"
        assert {p.pid for p in _reaper.find_session_processes(theirs)} == {b.pid}
    finally:
        _reap_all(a, b)


def test_it_does_not_touch_an_unmarked_process():
    token = _reaper.new_token()
    marked, plain = _spawn(token), _spawn(None)
    try:
        time.sleep(0.8)
        _reaper.reap(token)
        assert _reaper.wait_until_gone(token, timeout=8.0)
        assert plain.poll() is None, "an unmarked process was killed"
    finally:
        _reap_all(marked, plain)


def test_reaping_nothing_reports_nothing():
    """0 is the answer for a clean session, and it has to be distinguishable
    from the reaper not running at all - which is why reap() returns a count."""
    assert _reaper.reap(_reaper.new_token()) == 0


def test_an_empty_token_never_matches_even_a_process_that_carries_an_empty_one():
    """A falsy token must not degenerate into a match.

    The obvious version of this test - spawn nothing, assert an empty token
    finds nothing - passes with the guard REMOVED, because a process without
    the variable answers None and None never equals "". It proved nothing. The
    case that actually separates the two is a process whose token IS the empty
    string: without the guard that is a match, and a session that failed before
    minting a token would reap it.
    """
    victim = _spawn(None)
    try:
        # Set the variable to empty rather than leaving it out entirely.
        env = dict(os.environ)
        env[_reaper.TOKEN_VAR] = ""
        empty = subprocess.Popen(
            [sys.executable, "-c", f"import time; time.sleep({_SLEEP})"], env=env
        )
    except Exception:  # pragma: no cover
        _reap_all(victim)
        raise
    try:
        time.sleep(0.8)
        assert _reaper.find_session_processes("") == []
        assert _reaper.reap("") == 0
        assert empty.poll() is None, "an empty token reaped a live process"
    finally:
        _reap_all(victim, empty)


@pytest.mark.skipif(os.name != "nt", reason="job objects are a Windows mechanism")
def test_the_tree_dies_when_this_process_is_KILLED_not_merely_closed():
    """The path that in-process cleanup cannot reach, and the actual bug.

    Measured first, and it corrected the diagnosis: an exception out of the
    `with` block does NOT leak - __exit__ runs, Playwright tears down, zero
    survivors over an interleaved A/B with the reaper disabled. The leak was
    the timeout path, where the runner is killed and __exit__ never executes.
    With a real browser: eight survivors on the first attempt, twelve on the
    second; zero after this.

    Reproduced here without a browser, because the mechanism is the kernel's
    and not the browser's: a child binds a marked grandchild to its job, then
    is killed outright. The grandchild must not outlive it.
    """
    holder = subprocess.Popen(
        [sys.executable, "-c",
         "import subprocess,sys,time;"
         "sys.path.insert(0, r'" + os.path.dirname(os.path.dirname(
             os.path.abspath(_reaper.__file__))) + "');"
         "from invisible_playwright import _reaper;"
         "tok=_reaper.new_token();"
         "env=_reaper.stamp(dict(__import__('os').environ), tok);"
         f"kid=subprocess.Popen([sys.executable,'-c','import time; time.sleep({_SLEEP})'],env=env);"
         "n=_reaper.bind_tree_to_this_process(tok);"
         "print(kid.pid, n, flush=True);"
         f"time.sleep({_SLEEP})"],
        stdout=subprocess.PIPE, text=True,
    )
    try:
        line = holder.stdout.readline().split()
        assert len(line) == 2, f"the holder did not report: {line!r}"
        kid_pid, bound = int(line[0]), int(line[1])
        assert bound >= 1, "nothing was bound to the job, so nothing is guaranteed"
        assert psutil.pid_exists(kid_pid)

        psutil.Process(holder.pid).kill()   # no __exit__, no finally, no atexit
        holder.wait(timeout=10)

        deadline = time.time() + 10
        while time.time() < deadline and psutil.pid_exists(kid_pid):
            time.sleep(0.2)
        assert not psutil.pid_exists(kid_pid), (
            f"pid {kid_pid} outlived the process that owned its job - this is "
            "exactly the leak"
        )
    finally:
        _reap_all(holder)


def test_binding_reports_zero_rather_than_claiming_a_guarantee_it_lacks():
    """0 means the guarantee is NOT in place, and callers can tell.

    An empty token cannot identify anything, so there is nothing to bind. The
    honest answer is 0, not a silently successful no-op.
    """
    assert _reaper.bind_tree_to_this_process("", wait=0.5) == 0


def test_a_process_whose_environment_cannot_be_read_is_left_alone():
    """Kill on POSITIVE identification only.

    AccessDenied is the normal answer for another user's or an elevated
    process. Answering 'not ours' is the safe direction, and it must not be an
    exception either - one unreadable process cannot abort the whole sweep.
    """
    class Unreadable:
        def environ(self):
            raise psutil.AccessDenied(pid=1)

    assert _reaper._carries(Unreadable(), "anything") is False
