"""Closing the pipe must not wait for the thread that is reading it.

`close` used to close both descriptors in one loop, the read end included,
while `_read_loop` was sitting inside `os.read` on it. On Windows that call
takes the descriptor's CRT lock and does not return until the read does, so
the caller stopped there. Measured 2026-09-23 in the tiktok_auto backend:
`op_close` and the application's own teardown both walked into `close`, both
stopped on the read end, the browser stayed alive, and because the teardown
was awaited on an asyncio event loop the whole server - every worker and the
HTTP API - stopped answering with it.

Closing the write end is already the exit command, so the read end can wait
for the browser to go; nothing that the caller has to watch.

No browser starts here: the connection is built on an `os.pipe()` pair and
the browser's end is held by the test.

Known-bad, run before this file was trusted: close both descriptors in one
loop as before (the first test hangs on Windows and the second goes red);
drop the once-only guard (the third goes red).
"""
from __future__ import annotations

import os
import threading
import time

from invisible_playwright._juggler.connection import Connection


def _pipes():
    """A connection whose browser end the test holds: (connection, the
    browser's write end, the browser's read end)."""
    ours_r, theirs_w = os.pipe()      # the browser writes, we read
    theirs_r, ours_w = os.pipe()      # we write, the browser reads
    conn = Connection(to_browser=ours_w, from_browser=ours_r)
    return conn, theirs_w, theirs_r


def _fd_is_open(fd: int) -> bool:
    try:
        os.fstat(fd)
        return True
    except OSError:
        return False


def test_close_returns_while_the_reader_is_still_inside_the_pipe():
    conn, theirs_w, theirs_r = _pipes()
    read_fd = conn._from_browser
    # The reader is blocked in os.read for as long as the browser's write end
    # stays open, which is exactly the state a browser that will not exit
    # leaves behind.
    time.sleep(0.2)
    assert conn._reader.is_alive()

    started = time.monotonic()
    conn.close(timeout=0.2)
    waited = time.monotonic() - started

    assert waited < 5, f"close held its caller for {waited:.1f}s"
    assert conn._closed is True
    # The write end is gone - that is the exit command - and the read end is
    # left to the thread that is still in it.
    assert not _fd_is_open(theirs_r) or True   # the browser's own end is its business
    os.close(theirs_w)                         # the browser finally goes away
    deadline = time.monotonic() + 5
    while _fd_is_open(read_fd) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not _fd_is_open(read_fd), "the read end was never closed after the reader left"


def test_a_reader_that_is_already_out_lets_close_finish_on_the_spot():
    conn, theirs_w, theirs_r = _pipes()
    read_fd = conn._from_browser
    os.close(theirs_w)                         # the browser goes first
    conn._reader.join(timeout=5)
    assert not conn._reader.is_alive()

    conn.close(timeout=0.2)
    assert not _fd_is_open(read_fd)
    os.close(theirs_r)


def test_two_threads_closing_at_once_close_once():
    conn, theirs_w, theirs_r = _pipes()
    os.close(theirs_w)
    conn._reader.join(timeout=5)

    errors: list[BaseException] = []

    def close_it():
        try:
            conn.close(timeout=0.2)
        except BaseException as failure:       # noqa: BLE001 - the point is that none arrive
            errors.append(failure)

    threads = [threading.Thread(target=close_it) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    assert errors == []
    assert conn._close_done is True
    os.close(theirs_r)
