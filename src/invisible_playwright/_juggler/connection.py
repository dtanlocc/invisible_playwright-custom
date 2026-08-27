"""The connection to Juggler: the pipe, with no Node in between.

THE CONTRACT, read from `juggler/pipe/nsRemoteDebuggingPipe.cpp` and not
guessed:

  - messages are JSON delimited by a ZERO BYTE, not a newline
    (`ReaderLoop` accumulates until it finds `'\\0'`);
  - on POSIX the descriptors are **hardwired to 3 and 4**: `const int
    readFD = 3; const int writeFD = 4;`. They are not negotiated;
  - on Windows there are NO descriptors: they are HANDLEs read from the
    environment, `GetEnvironmentVariableA("PW_PIPE_READ", ...)` plus
    `atoi`, so the value must be passed in DECIMAL and the handle must be
    made inheritable;
  - the names are from the BROWSER's point of view: its `PW_PIPE_READ` is
    what IT reads from, i.e. where WE write.

⛔ And the flag `-juggler-pipe` must appear on the command line, or on
Windows the handles never get armed at all and the pipe breaks at the
launcher -> parent transition.

⛔ THE READINESS SIGNAL DOES NOT TRAVEL OVER THE PIPE. The browser prints
`Juggler listening to the pipe` on stdout, and that line comes out of a
`dump()` that a `MOZILLA_OFFICIAL` build disables: a disabled `dump()`
RETURNS SUCCESSFULLY without writing. The fix lives in the Firefox source
(`30-upstream-playwright-patches.md`), not here. Anyone reading a long
timeout at launch should look there first.

State: first piece. Opens the connection, sends commands, receives
responses and events. Not yet a client: no lifecycle, no frames, no
actionability.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from typing import Any, Callable, Optional

NUL = b"\x00"
_READY = "Juggler listening to the pipe"


class ProtocolError(RuntimeError):
    """The browser refused a command. Carries its message, not ours.

    ⛔ `checkScheme` is CLOSED WORLD: an undeclared field is not ignored,
    it is rejected, and it happens at RUNTIME. The browser's message is
    the only thing that says which field.
    """


class Connection:
    """A pipe to an already-launched Firefox."""

    def __init__(self, to_browser, from_browser, process=None):
        self._to_browser = to_browser      # where WE write
        self._from_browser = from_browser  # where WE read
        self._process = process
        self._next_id = 0
        self._pending: dict[int, list] = {}
        self._lock = threading.Lock()
        self._closed = False
        self._error: Optional[BaseException] = None
        #: (method, params, sessionId|None). The third argument is what
        #: distinguishes two pages open at the same time.
        self.on_event: Callable[[str, dict, Optional[str]], None] = (
            lambda method, params, session: None)
        #: Every exception `on_event` raised, as "method: message". Bounded at
        #: 32 so a handler that raises on every event cannot eat memory.
        #: ⛔ READ THIS IN A TEST. An empty event list plus an empty
        #: `handler_errors` means the browser sent nothing; an empty event list
        #: with entries HERE means your handler is broken, and those are two
        #: completely different bugs that used to look identical.
        self.handler_errors: list = []
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    # ── reading ─────────────────────────────────────────────────────────────
    def _read_loop(self) -> None:
        buffer = b""
        try:
            while not self._closed:
                chunk = os.read(self._from_browser, 65536)
                if not chunk:
                    break
                buffer += chunk
                while NUL in buffer:
                    raw, buffer = buffer.split(NUL, 1)
                    if raw:
                        self._deliver(raw)
        except OSError as e:
            self._error = e
        finally:
            self._closed = True
            # ⛔ Whoever is waiting must be WOKEN UP, not left to the
            # timeout: a closed pipe is information, and delivering it
            # thirty seconds later as "no response" hides what happened.
            with self._lock:
                pending = list(self._pending.values())
                self._pending.clear()
            for ready, box in pending:
                box.append({"error": {"message": "the pipe closed"}})
                ready.set()

    def _deliver(self, raw: bytes) -> None:
        try:
            msg = json.loads(raw.decode("utf-8"))
        except Exception:
            return
        msg_id = msg.get("id")
        if msg_id is None:
            method = msg.get("method")
            if method:
                # ⛔ The `sessionId` must be delivered together with the
                # event. Without it, the events of TWO pages open at the
                # same time are indistinguishable, and whoever is
                # waiting for a `load` gets the other tab's. It is not a
                # rare case: it is what happens on the second
                # `new_page()`.
                try:
                    self.on_event(method, msg.get("params") or {},
                                  msg.get("sessionId"))
                except Exception as failure:
                    # ⛔ SWALLOWING IT IS RIGHT, LOSING IT IS NOT. A handler
                    # that raises must not kill the read loop, or one bad
                    # callback takes the whole connection down. But a bare
                    # `pass` here makes the failure INVISIBLE, and that is not
                    # a theory: `test_python_talks_to_juggler_without_node`
                    # installed a two-argument lambda where this call passes
                    # three, so every delivery raised TypeError, the event list
                    # stayed empty and the test could never pass. Nobody saw it
                    # because the test is marked e2e and the default selection
                    # deselects it - the exception had nowhere to be seen even
                    # when it did run.
                    if len(self.handler_errors) < 32:
                        self.handler_errors.append(
                            "%s: %s" % (method, failure))
            return
        with self._lock:
            entry = self._pending.pop(msg_id, None)
        if entry is not None:
            ready, box = entry
            box.append(msg)
            ready.set()

    # ── writing ─────────────────────────────────────────────────────────────
    def send(self, method: str, params: Optional[dict] = None,
             session: Optional[str] = None, timeout: float = 30.0) -> Any:
        if self._closed:
            raise ProtocolError("the pipe is closed: %s" % (self._error or ""))
        with self._lock:
            self._next_id += 1
            msg_id = self._next_id
            # An EVENT, not a `sleep` loop: the wakeup comes from the
            # reader thread when the response is there, instead of from
            # the next tick of a `time.sleep(0.002)`.
            #
            # ⛔ And what this line did NOT fix also belongs here,
            # because the first draft of this comment cited a false
            # measurement. It said "a BARE command cost 26.8 ms": that
            # command was `Heap.collectGarbage`, **which really does
            # collect garbage**, and it still costs 23.1 ms even after
            # the change. The real latency of the pipe, measured on
            # 2026-08-27 on commands that do no work, is **2.4 ms** for
            # `Runtime.evaluate("1")` and 4.3 ms for
            # `Page.getContentQuads`. Picking an expensive command as
            # the sample of "bare" attributes the browser's own time to
            # the transport.
            box: list = []
            ready = threading.Event()
            self._pending[msg_id] = (ready, box)
        msg: dict = {"id": msg_id, "method": method, "params": params or {}}
        if session:
            msg["sessionId"] = session
        os.write(self._to_browser, json.dumps(msg).encode("utf-8") + NUL)

        if not ready.wait(timeout):
            with self._lock:
                self._pending.pop(msg_id, None)
            raise ProtocolError(
                "%s: no response in %.0fs. If this is the FIRST command, "
                "look at the readiness signal before the pipe."
                % (method, timeout))
        response = box[0]
        if "error" in response:
            e = response["error"]
            raise ProtocolError("%s: %s" % (method, e.get("message", e)))
        return response.get("result")

    def close(self, timeout: float = 5.0) -> None:
        """Closes the pipe and waits for the browser to exit on its own.

        ⛔ Do NOT start from `terminate()`, and the reason is measured in
        this project: on Windows the pid that `Popen` returns is the
        LAUNCHER stub, which exits after about a second, so by the time
        of the kill the browser's tree is no longer its child and
        survives. Counted in one day: 88 orphaned processes.

        The clean path goes through the contract:
        `nsRemoteDebuggingPipe::ReaderLoop` calls `Disconnected` when the
        read returns zero, and Juggler shuts the browser down. Closing
        the pipe IS the exit command. `terminate()` remains only as a
        last resort, for whatever did not die on its own.
        """
        self._closed = True
        for fd in (self._to_browser, self._from_browser):
            try:
                os.close(fd)
            except OSError:
                pass
        p = self._process
        if not p:
            return
        deadline = time.monotonic() + timeout
        while p.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        if p.poll() is None:
            try:
                p.terminate()
            except OSError:
                pass


# ── launch ──────────────────────────────────────────────────────────────────

def _spawn_windows(executable, argv, env):
    import _winapi
    import msvcrt

    def inheritable(h):
        """⛔ CPython's `_winapi.CreatePipe` calls Windows' CreatePipe with
        NULL security attributes, so the handles are NOT inheritable.
        Passing them in `handle_list` as they were made `CreateProcess`
        fail with `WinError 87 - The parameter is incorrect`, which does
        not name the cause. They get duplicated asking for inheritance,
        and the original is closed."""
        current_process = _winapi.GetCurrentProcess()
        new = _winapi.DuplicateHandle(current_process, h, current_process,
                                      0, True, _winapi.DUPLICATE_SAME_ACCESS)
        _winapi.CloseHandle(h)
        return new

    # Two pipes. The names follow the BROWSER's point of view, like the
    # environment it will read: "read" is what it reads from, so where
    # WE write.
    its_read, our_write = _winapi.CreatePipe(0, 0)
    our_read, its_write = _winapi.CreatePipe(0, 0)
    its_read, its_write = inheritable(its_read), inheritable(its_write)

    env = dict(env)
    # `atoi` on the C++ side: the value must be DECIMAL.
    env["PW_PIPE_READ"] = str(int(its_read))
    env["PW_PIPE_WRITE"] = str(int(its_write))

    si = subprocess.STARTUPINFO()
    si.lpAttributeList = {"handle_list": [int(its_read), int(its_write)]}
    # `handle_list` REQUIRES close_fds=True: it is the only way Windows
    # inherits exactly those two handles and nothing else.
    p = subprocess.Popen([executable] + argv, env=env, startupinfo=si,
                         close_fds=True, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT)
    # The child's ends no longer serve us: keeping them open would
    # prevent us from noticing that the browser has closed.
    _winapi.CloseHandle(its_read)
    _winapi.CloseHandle(its_write)
    return (msvcrt.open_osfhandle(our_write, 0),
            msvcrt.open_osfhandle(our_read, os.O_RDONLY), p)


def _spawn_posix(executable, argv, env):
    its_read, our_write = os.pipe()
    our_read, its_write = os.pipe()

    def fix_descriptors():
        # On POSIX the numbers are HARDWIRED in the C++: 3 for reading,
        # 4 for writing.
        os.dup2(its_read, 3)
        os.dup2(its_write, 4)

    p = subprocess.Popen([executable] + argv, env=env,
                         preexec_fn=fix_descriptors,
                         pass_fds=(its_read, its_write),
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    os.close(its_read)
    os.close(its_write)
    return our_write, our_read, p


def launch(executable: str, profile_dir: str, *, headless: bool = True,
          argv_extra: Optional[list] = None, env: Optional[dict] = None,
          ready_timeout: float = 60.0) -> Connection:
    """Launches Firefox over the pipe and returns an already-ready
    connection."""
    argv = ["-no-remote"]
    if headless:
        argv.append("-headless")
    else:
        argv += ["-wait-for-browser", "-foreground"]
    argv += ["-profile", profile_dir, "-juggler-pipe"]
    argv += list(argv_extra or [])
    argv.append("-silent")

    full_env = dict(os.environ if env is None else env)
    spawn = _spawn_windows if sys.platform == "win32" else _spawn_posix
    to_browser, from_browser, p = spawn(executable, argv, full_env)

    # ⛔ Readiness is read on stdout, not on the pipe, and the line may
    # not come out at all on a MOZILLA_OFFICIAL build without the fix in
    # Juggler. It waits for the line, but it does NOT die if it does not
    # arrive: it tries to talk anyway, so the failure mode is a protocol
    # error naming the command instead of a silent timeout.
    seen = _wait_until_ready(p, ready_timeout)
    c = Connection(to_browser, from_browser, p)
    c.ready_seen = seen
    return c


def _wait_until_ready(p, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if p.poll() is not None:
            return False
        line = p.stdout.readline()
        if not line:
            time.sleep(0.01)
            continue
        if _READY in line.decode("utf-8", "replace"):
            return True
    return False
