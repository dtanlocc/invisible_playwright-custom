"""The seam where Node stops being necessary, exercised through the PUBLIC API.

⛔ THE POINT OF THESE TESTS IS THAT THEY DO NOT KNOW ABOUT `_juggler`. They call
`InvisiblePlaywright` exactly the way a user does, and the only thing that
changes is one environment variable. A test written against the server directly
would prove the server works and say nothing about the thing that matters: that
823 generated API methods, the channel layer, the guid registry and the sync
facade all still function with a different object underneath them.
"""
from __future__ import annotations

import http.server
import os
import socketserver
import threading

import pytest

from invisible_playwright._juggler import factory

PAGE = b"""<!doctype html><html><head><title>seam</title></head><body>
<button id=b onclick="this.dataset.n=(+(this.dataset.n||0)+1)">press</button>
<input id=f>
<div id=t>hello</div>
</body></html>"""


def _serve(body):
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    return H


# ── without a browser ───────────────────────────────────────────────────────

def test_an_unknown_transport_is_REFUSED_not_silently_the_default(monkeypatch):
    """⛔ THE KNOWN-BAD OF THE SWITCH. A typo would otherwise run the driver
    while the caller believed they were measuring the Python path, and every
    number taken that way would describe the wrong arm. This project has a rule
    about a bench arm that is not what it says it is."""
    monkeypatch.setenv(factory.CHOICE_ENV, "jugler")
    with pytest.raises(ValueError) as failure:
        factory.chosen()
    assert "jugler" in str(failure.value)
    assert factory.JUGGLER in str(failure.value), (
        "the refusal does not say what the valid names are")


def test_the_default_is_the_DRIVER_while_the_server_matures(monkeypatch):
    """⛔ A half-finished server that silently became the default would turn
    every user session into an experiment. It flips when the judgement says it
    can, not when the code looks done."""
    monkeypatch.delenv(factory.CHOICE_ENV, raising=False)
    assert factory.chosen() == factory.DRIVER


def test_the_serializer_TAGS_values_instead_of_sending_them_bare():
    """⛔ Playwright does not send JSON, it sends a tagged union, and
    `parse_value` reads the tag. A bare `True` where `{"b": true}` is expected
    does not raise: it falls through to the object branch and comes back as
    something else entirely."""
    from invisible_playwright._juggler.server import _serialize
    assert _serialize(None) == {"v": "null"}
    assert _serialize(True) == {"b": True}
    assert _serialize(3) == {"n": 3}
    assert _serialize("x") == {"s": "x"}
    assert _serialize([1, "a"]) == {"a": [{"n": 1}, {"s": "a"}]}
    assert _serialize({"k": 1}) == {"o": [{"k": "k", "v": {"n": 1}}]}
    # ⛔ A bool is an int in Python, so the order of the checks is the whole
    # correctness of this function: reversed, `True` would leave as `{"n": 1}`.
    assert _serialize(False) == {"b": False}


def test_an_object_the_server_never_created_is_REFUSED_by_name():
    """A guid that is not in the registry must say so, not raise KeyError."""
    from invisible_playwright._juggler.dispatcher import ProtocolException
    from invisible_playwright._juggler.server import JugglerServer
    server = JugglerServer()
    with pytest.raises(ProtocolException) as failure:
        server.handle({"id": 1, "guid": "page@99", "method": "close",
                       "params": {}})
    assert "page@99" in str(failure.value)


def test_an_out_of_perimeter_object_refuses_with_a_REASON():
    """⛔ Section 5.4: out of perimeter fails LOUDLY. Never a no-op, never an
    AttributeError - a reason the caller can act on."""
    from invisible_playwright._juggler.dispatcher import ProtocolException
    from invisible_playwright._juggler.server import (JugglerServer,
                                                      TracingDispatcher)
    server = JugglerServer()
    tracing = TracingDispatcher(server, None)
    with pytest.raises(ProtocolException) as failure:
        tracing.call("tracingStart", {})
    message = str(failure.value)
    assert "Tracing" in message and "tracingStart" in message
    assert "deliberate refusal" in message, (
        "the refusal does not distinguish itself from a gap: %s" % message)


def test_create_is_announced_BEFORE_anything_can_name_the_object():
    """⛔ `Connection.dispatch` looks the guid up in a plain dict and raises
    `Cannot find object` when it is missing, so an out-of-order create is not a
    race that usually works - it is a hard failure."""
    from invisible_playwright._juggler.dispatcher import Dispatcher, Server

    sent: list = []

    class Recording:
        def emit_message(self, message):
            sent.append(message)

    class Thing(Dispatcher):
        TYPE = "Thing"

    server = Server()
    server.attach(Recording())
    thing = Thing(server, None, {"a": 1})
    assert sent, "nothing was announced at all"
    first = sent[0]
    assert first["method"] == "__create__"
    assert first["params"]["guid"] == thing.guid
    assert first["params"]["initializer"] == {"a": 1}
    assert first["guid"] == "", "a top-level object must be parented to Root"


# ── with a browser, through the public API ──────────────────────────────────

@pytest.mark.e2e
def test_the_public_API_drives_a_page_WITHOUT_node(firefox_binary):
    """⛔ THE TEST THIS WHOLE SUBSYSTEM EXISTS FOR.

    Nothing below mentions `_juggler`. It is the ordinary user-facing API, and
    the only difference from any other session is one environment variable. If
    this passes, the channel layer, the guid registry, the object factory, the
    823 generated methods and the sync facade are all working against a
    different object underneath - which is the entire claim of the detachment.
    """
    os.environ[factory.CHOICE_ENV] = factory.JUGGLER
    srv = socketserver.TCPServer(("127.0.0.1", 0), _serve(PAGE))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = "http://127.0.0.1:%d/" % srv.server_address[1]
    from invisible_playwright import InvisiblePlaywright
    try:
        with InvisiblePlaywright(seed=42, binary_path=firefox_binary,
                                 headless=True) as browser:
            page = browser.new_page()
            page.goto(url)
            assert page.title() == "seam"
            assert "hello" in page.content()
            page.click("#b")
            page.fill("#f", "typed")
            assert page.input_value("#f") == "typed"
            assert page.text_content("#t") == "hello"
            assert page.is_visible("#b")
            box = page.query_selector("#b").bounding_box()
            assert box and box["width"] > 0
    finally:
        os.environ.pop(factory.CHOICE_ENV, None)
        srv.shutdown()
