"""Records the Playwright protocol a real session exchanges with the driver.

⛔ THIS EXISTS SO THE PYTHON SERVER IS WRITTEN AGAINST THE WIRE, NOT AGAINST A
GUESS. `_juggler` has to answer `_connection.py` with the same messages the Node
driver answers: the same object types, the same guid parentage, the same
initializer FIELDS, the same events in the same order. Every one of those can be
deduced from reading `_impl`, and every deduction is a place to be subtly wrong -
a missing initializer key does not fail at the seam, it fails much later, inside
a property nobody looks at.

Reading `_impl` tells you which fields are CONSUMED. It cannot tell you which
fields are SENT, and the difference is exactly the set of fields a future code
path will want.

    python scripts/capture_protocol.py <firefox-binary> [-o trace.json]

The trace is a list of `{"dir": "send"|"recv", "msg": {...}}` in order. It runs
a deliberately ordinary session - launch, context, page, goto, click, close -
against a LOCAL server, so nothing leaves the machine and no site is named.
"""
from __future__ import annotations

import argparse
import http.server
import json
import os
import pathlib
import socketserver
import sys
import threading

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

# ⛔ THE DRIVER ARM IMPORTS AN OLDER TREE, and the line above would otherwise
# beat it. `INVPW_DRIVER_TREE` names a git worktree at the last commit that
# carried the Node driver, and on the driver arm that tree's package has to WIN
# the import - a `PYTHONPATH` from the caller does not, because the insert
# above runs afterwards and goes in front of it.
#
# ⛔ Only the PACKAGE comes from there. This recorder stays this tree's: two
# traces produced by two different instruments measure the instruments, which
# is the mistake the comparison exists to avoid.
if (os.environ.get("INVPW_TRANSPORT") == "driver"
        and os.environ.get("INVPW_DRIVER_TREE")):
    sys.path.insert(0, str(pathlib.Path(os.environ["INVPW_DRIVER_TREE"]) / "src"))

PAGE = b"""<!doctype html><html><head><title>capture</title></head><body>
<button id=b onclick="this.textContent='clicked'">press</button>
<input id=f>
</body></html>"""


def _serve():
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(PAGE)))
            self.end_headers()
            self.wfile.write(PAGE)

        def log_message(self, *a):
            pass
    return H


def capture(binary: str, out: pathlib.Path) -> int:
    from invisible_playwright._pw._impl import _transport as T

    trace: list = []

    # ⛔ The recording wraps the TRANSPORT, not the Connection: at this seam the
    # messages are still exactly what crosses the pipe. One level up they have
    # already been turned into ChannelOwners, which is the thing being rebuilt.
    # ⛔ BOTH TRANSPORTS, not just the driver's. The whole point of a
    # capture is to compare the two arms, and hooking only `PipeTransport`
    # produces an empty trace on the Python arm - which reads as "the session
    # sent nothing" rather than as "the recorder was pointed at the wrong
    # class". The Python one is imported lazily so this script still runs in a
    # tree where it does not exist.
    hooked = []
    classes = []
    # ⛔ BOTH ARE OPTIONAL NOW. `PipeTransport` went with the Node driver on
    # 2026-08-28, so naming it unconditionally turned this recorder into an
    # `AttributeError` in a tree that no longer has it - on the very script
    # whose job is to compare that tree against one that does.
    if hasattr(T, "PipeTransport"):
        classes.append(T.PipeTransport)
    try:
        from invisible_playwright._juggler.transport import InProcessTransport
        classes.append(InProcessTransport)
    except Exception:
        pass
    if not classes:
        raise SystemExit(
            "no transport class to hook: neither PipeTransport nor "
            "InProcessTransport is importable, so a trace would be empty and "
            "read as a session that sent nothing")

    for cls in classes:
        real_send = cls.send

        def make(real):
            def send(self, message):
                trace.append({"dir": "send", "msg": message})
                return real(self, message)
            return send

        cls.send = make(real_send)
        hooked.append(cls.__name__)

    real_init = T.Transport.__init__

    def init(self, loop):
        real_init(self, loop)
        outer = self

        class Hook:
            def __set_name__(self, *a):
                pass

        # `on_message` is a plain attribute the Connection overwrites, so it is
        # wrapped after the Connection has installed its own.
        outer._trace = trace

    T.Transport.__init__ = init

    real_dispatch_setter = None

    from invisible_playwright._pw._impl._connection import Connection
    real_conn_init = Connection.__init__

    def conn_init(self, dispatcher_fiber, object_factory, transport, loop,
                  local_utils=None):
        real_conn_init(self, dispatcher_fiber, object_factory, transport, loop,
                       local_utils)
        inner = transport.on_message

        def on_message(msg):
            trace.append({"dir": "recv", "msg": msg})
            inner(msg)

        transport.on_message = on_message

    Connection.__init__ = conn_init

    srv = socketserver.TCPServer(("127.0.0.1", 0), _serve())
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = "http://127.0.0.1:%d/" % srv.server_address[1]

    from invisible_playwright import InvisiblePlaywright
    try:
        with InvisiblePlaywright(seed=42, binary_path=binary,
                                 headless=True) as browser:
            page = browser.new_page()
            page.goto(url)
            page.click("#b")
            page.fill("#f", "hello")
            page.title()
            page.content()
            page.close()
    finally:
        srv.shutdown()

    out.write_bytes(json.dumps(trace, indent=1).encode("utf-8"))
    inviati = sum(1 for x in trace if x["dir"] == "send")
    ricevuti = len(trace) - inviati
    print("wrote %s: %d messages (%d sent, %d received) [hooked: %s]"
          % (out, len(trace), inviati, ricevuti, ", ".join(hooked)))
    if not inviati:
        raise SystemExit(
            "the trace has no OUTGOING message, which no real session can "
            "produce: the recorder is hooked to a transport this run did not "
            "use. Hooked: %s" % ", ".join(hooked))

    metodi = sorted({x["msg"].get("method", "?") for x in trace
                     if x["dir"] == "send"})
    tipi = sorted({(x["msg"].get("params") or {}).get("type")
                   for x in trace if x["dir"] == "recv"
                   and x["msg"].get("method") == "__create__"} - {None})
    print("  methods sent:   %s" % ", ".join(metodi))
    print("  object types:   %s" % ", ".join(tipi))
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("binary")
    p.add_argument("-o", "--out", default=str(ROOT / "protocol_trace.json"))
    a = p.parse_args()
    return capture(a.binary, pathlib.Path(a.out))


if __name__ == "__main__":
    sys.exit(main())
