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
<ul><li class=x>one</li><li class=x>two</li><li class=x>three</li></ul>
<input id=c type=checkbox>
<select id=s><option value=a>A</option><option value=b>B</option></select>
<div id=late></div>
<a id=next href="/second">go</a>
<script>
  setTimeout(function () {
    document.getElementById('late').innerHTML = '<span id=slow>arrived</span>';
  }, 800);
</script>
</body></html>"""

SECOND = b"""<!doctype html><html><head><title>second</title></head>
<body><div id=t>page two</div></body></html>"""


def _serve(body):
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            page = SECOND if self.path.startswith("/second") else body
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)

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
    # ⛔ A CONTAINER MUST CARRY AN `id`. `parse_value` writes
    # `refs[value["id"]]` unconditionally, so its absence is a bare KeyError
    # from inside the client, several frames away from the cause. The ids are
    # what lets a cyclic structure point back at itself; we never emit a `ref`,
    # but the reader indexes on the id anyway.
    assert _serialize([1, "a"]) == {"a": [{"n": 1}, {"s": "a"}], "id": 1}
    assert _serialize({"k": 1}) == {"o": [{"k": "k", "v": {"n": 1}}], "id": 1}
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


@pytest.mark.e2e
def test_the_public_API_reads_MANY_elements_without_node(firefox_binary):
    """`query_selector_all`, `count` and `eval_on_selector_all`.

    ⛔ Each handle holds a DOM node alive until it is disposed, so a page with a
    thousand matches leaks a thousand nodes. That is a property of the protocol,
    not of this test, and it is written down where the handles are made.
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
            found = page.query_selector_all("li.x")
            assert len(found) == 3, "query_selector_all returned %d" % len(found)
            assert [h.text_content() for h in found] == ["one", "two", "three"]
            assert page.eval_on_selector("#t", "el => el.textContent") == "hello"
            assert page.eval_on_selector_all(
                "li.x", "els => els.length") == 3
    finally:
        os.environ.pop(factory.CHOICE_ENV, None)
        srv.shutdown()


@pytest.mark.e2e
def test_the_public_API_WAITS_for_an_element_that_arrives_late(firefox_binary):
    """⛔ THE POINT OF `wait_for_selector`, and the reason it cannot go through
    the retry loop: that loop disposes what it resolves on every turn, so it
    would hand back a handle it has just released - and a released handle does
    not raise, it answers wrong. The element below arrives after 800 ms."""
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
            assert page.query_selector("#slow") is None, (
                "the element was already there: the test proves nothing")
            handle = page.wait_for_selector("#slow", timeout=8000)
            assert handle is not None
            assert handle.text_content() == "arrived"
    finally:
        os.environ.pop(factory.CHOICE_ENV, None)
        srv.shutdown()


@pytest.mark.e2e
@pytest.mark.xfail(reason="[B185] Page.goBack answers success and does nothing "
                          "in the shipped engine - the Node driver fails the "
                          "same way, so this is not the server",
                   strict=True)
def test_the_public_API_navigates_BACK_and_FORWARD_without_node(firefox_binary):
    """⛔ XFAIL ON AN ENGINE DEFECT, MEASURED ON BOTH ARMS.

    `Page.goBack` answers `{success: true}` and then nothing happens: no
    navigation event, no state change, the title stays on the page you were
    already on. Measured on 2026-08-27 with `history.length == 2`, so the
    history entries exist and the command simply does not act on them.

    The control is what makes this an engine defect rather than a gap here: the
    SAME call through the Node driver, same binary, times out with `waiting for
    navigation until load`. Two different clients, one engine, one behaviour.

    `strict=True` on purpose: the day the engine is fixed this must turn RED so
    somebody deletes the xfail, instead of quietly passing forever as an
    expected failure that is no longer failing.
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
            page.goto(url + "second")
            assert page.title() == "second"
            # ⛔ A SHORT TIMEOUT because this failure is EXPECTED: at the
            # default 30 seconds the xfail holds a browser open for half a
            # minute, and the tests running beside it start failing on load.
            # That is the rule about never measuring under load, applied to the
            # bench itself.
            page.go_back(timeout=3000)
            assert page.title() == "seam"
            page.go_forward()
            assert page.title() == "second"
            page.reload()
            assert page.title() == "second"
    finally:
        os.environ.pop(factory.CHOICE_ENV, None)
        srv.shutdown()


@pytest.mark.e2e
def test_set_content_runs_in_the_MAIN_world_without_node(firefox_binary):
    """⛔ THE KNOWN-BAD OF `set_content`. Run from the utility world it answers
    `The operation is insecure` EVERY time: that world has an extended
    principal, and Gecko requires `document.open()` to run under a principal
    equal to the document's. The fork already fixed this inside the driver; the
    Python server has to get it right for the same reason, not by luck.
    """
    os.environ[factory.CHOICE_ENV] = factory.JUGGLER
    from invisible_playwright import InvisiblePlaywright
    try:
        with InvisiblePlaywright(seed=42, binary_path=firefox_binary,
                                 headless=True) as browser:
            page = browser.new_page()
            page.set_content("<html><head><title>written</title></head>"
                             "<body><p id=w>from set_content</p></body></html>")
            assert page.title() == "written"
            assert page.text_content("#w") == "from set_content"
            # And an apostrophe in the html must not close the JavaScript
            # literal it travels inside: that is the 2026-08-24 defect.
            page.set_content("<p id=q>it's fine</p>")
            assert page.text_content("#q") == "it's fine"
    finally:
        os.environ.pop(factory.CHOICE_ENV, None)


@pytest.mark.e2e
def test_the_public_API_selects_and_checks_without_node(firefox_binary):
    """`select_option` and `check`, through the generated API."""
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
            assert page.input_value("#s") == "a"
            page.select_option("#s", "b")
            assert page.input_value("#s") == "b", (
                "a bare string picked the first option instead of the asked one")
            assert not page.is_checked("#c")
            page.check("#c")
            assert page.is_checked("#c")
            page.uncheck("#c")
            assert not page.is_checked("#c")
    finally:
        os.environ.pop(factory.CHOICE_ENV, None)
        srv.shutdown()


# ── closed shadow roots ─────────────────────────────────────────────────────

SHADOW = b"""<!doctype html><html><head><title>shadow</title></head><body>
<div id=host></div>
<div id=openhost></div>
<script>
  const closed = document.getElementById('host').attachShadow({mode: 'closed'});
  closed.innerHTML = '<p id=secret>hidden text</p><div id=inner></div>';
  const nested = closed.getElementById('inner')
      .attachShadow({mode: 'closed'});
  nested.innerHTML = '<p id=deep>two levels down</p>';
  const open_ = document.getElementById('openhost').attachShadow({mode: 'open'});
  open_.innerHTML = '<p id=visible>open text</p>';
</script>
</body></html>"""


@pytest.mark.e2e
def test_locators_reach_INSIDE_a_closed_shadow_root(firefox_binary):
    """⛔ Side A of the closed-shadow-root research, verified on the product.

    The engine patch lives in `Element::GetShadowRootForBindings` and is gated
    on the ExpandedPrincipal, so the utility world sees a closed root and the
    page does not. This asserts the automation half; the test below asserts
    the half that matters more - that the page gained nothing.
    """
    os.environ[factory.CHOICE_ENV] = factory.JUGGLER
    srv = socketserver.TCPServer(("127.0.0.1", 0), _serve(SHADOW))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = "http://127.0.0.1:%d/" % srv.server_address[1]
    from invisible_playwright import InvisiblePlaywright
    try:
        with InvisiblePlaywright(seed=42, binary_path=firefox_binary,
                                 headless=True) as browser:
            page = browser.new_page()
            page.goto(url)
            assert page.text_content("#secret") == "hidden text"
            assert page.text_content("#visible") == "open text"
            assert page.text_content("#deep") == "two levels down", (
                "a root nested inside a closed root was not reached")
    finally:
        os.environ.pop(factory.CHOICE_ENV, None)
        srv.shutdown()


@pytest.mark.e2e
def test_the_PAGE_still_sees_nothing_of_a_closed_root(firefox_binary):
    """⛔ THE HALF THAT MATTERS MORE, and it is the known-bad of the engine
    patch. A real Firefox NEVER hands a closed root to content: if our build
    did, `!!el.shadowRoot` on a closed host would be a one-line detector that
    no fingerprint suite would even need to be clever to run.

    So the assertion is not "automation works" but "the page is unchanged".
    """
    os.environ[factory.CHOICE_ENV] = factory.JUGGLER
    srv = socketserver.TCPServer(("127.0.0.1", 0), _serve(SHADOW))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = "http://127.0.0.1:%d/" % srv.server_address[1]
    from invisible_playwright import InvisiblePlaywright
    try:
        with InvisiblePlaywright(seed=42, binary_path=firefox_binary,
                                 headless=True) as browser:
            page = browser.new_page()
            page.goto(url)
            # `evaluate` runs in the page's own world, which is the whole
            # point: this is what a site would see.
            assert page.evaluate(
                "() => document.getElementById('host').shadowRoot") is None, (
                "the PAGE can see a closed shadow root: that is a one-line "
                "detector, and a real Firefox never does this")
            assert page.evaluate(
                "() => !!document.getElementById('openhost').shadowRoot"), (
                "an OPEN root stopped being visible to the page: the patch "
                "moved something it should not have touched")
            assert page.evaluate(
                "() => document.getElementById('host').outerHTML"
            ) == '<div id="host"></div>', (
                "the page's own serialisation changed")
    finally:
        os.environ.pop(factory.CHOICE_ENV, None)
        srv.shutdown()


@pytest.mark.e2e
def test_content_SERIALISES_shadow_roots_including_closed_ones(firefox_binary):
    """⛔ Side B of the research, and what forking the client unlocked.

    Upstream serialises with `documentElement.outerHTML`, which walks the light
    DOM only: every shadow root comes back as an empty host. This asserts the
    divergence is real and complete - open, closed, and a root NESTED inside a
    closed one, which is where a depth-one walk would look right and be wrong.
    """
    os.environ[factory.CHOICE_ENV] = factory.JUGGLER
    srv = socketserver.TCPServer(("127.0.0.1", 0), _serve(SHADOW))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = "http://127.0.0.1:%d/" % srv.server_address[1]
    from invisible_playwright import InvisiblePlaywright
    try:
        with InvisiblePlaywright(seed=42, binary_path=firefox_binary,
                                 headless=True) as browser:
            page = browser.new_page()
            page.goto(url)
            html = page.content()
            assert "hidden text" in html, (
                "the CLOSED root was not serialised: %s" % html[:400])
            assert "open text" in html, "the OPEN root was not serialised"
            assert "two levels down" in html, (
                "the nested root was not serialised: the walk stops at depth "
                "one, which looks right and is not")
            assert 'shadowrootmode="closed"' in html, (
                "the closed root was serialised without saying it was closed")
            # And the page's own serialisation is untouched: the difference
            # is ours, not the document's.
            # ⛔ ASSERT ON THE SERIALISED ROOT, NOT ON ITS TEXT. The first
            # version looked for "hidden text" and failed: that string is also
            # in the inline <script> that BUILDS the root, so it is present in
            # any serialisation of this page and proves nothing either way.
            own = page.evaluate("() => document.documentElement.outerHTML")
            assert "shadowrootmode" not in own, (
                "the page can serialise its own shadow roots: %s" % own[:200])
    finally:
        os.environ.pop(factory.CHOICE_ENV, None)
        srv.shutdown()


# ── events ──────────────────────────────────────────────────────────────────

NOISY = b"""<!doctype html><html><head><title>events</title></head><body>
<button id=alert onclick="window.alert('are you sure')">alert</button>
<button id=boom onclick="undefinedFunctionCall()">boom</button>
<script>
  console.log('first line', 42);
  console.warn('a warning');
</script>
</body></html>"""


@pytest.mark.e2e
def test_console_messages_reach_the_page_listener(firefox_binary):
    """⛔ `console` and `pageError` are emitted on the CONTEXT, not on the
    Page, and `_browser_context.py` re-emits them on the page it finds in
    `params["page"]`. Emitting them on the Page produces no error at all: the
    handler simply never runs, and the user concludes their page prints
    nothing."""
    os.environ[factory.CHOICE_ENV] = factory.JUGGLER
    srv = socketserver.TCPServer(("127.0.0.1", 0), _serve(NOISY))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = "http://127.0.0.1:%d/" % srv.server_address[1]
    from invisible_playwright import InvisiblePlaywright
    try:
        with InvisiblePlaywright(seed=42, binary_path=firefox_binary,
                                 headless=True) as browser:
            page = browser.new_page()
            seen = []
            page.on("console", lambda m: seen.append((m.type, m.text)))
            page.goto(url)
            page.wait_for_timeout(500)
            assert seen, "no console message arrived at all"
            kinds = {t for t, _ in seen}
            texts = " | ".join(text for _, text in seen)
            assert "first line" in texts, texts
            assert "42" in texts, (
                "the numeric argument was dropped: %s" % texts)
            assert "warning" in kinds or "warn" in kinds, (
                "the message type was lost: %s" % kinds)
    finally:
        os.environ.pop(factory.CHOICE_ENV, None)
        srv.shutdown()


@pytest.mark.e2e
def test_an_uncaught_error_reaches_the_pageerror_listener(firefox_binary):
    """A page that throws must reach `page.on("pageerror")`, with the message
    intact - that is the only way a caller learns the site broke."""
    os.environ[factory.CHOICE_ENV] = factory.JUGGLER
    srv = socketserver.TCPServer(("127.0.0.1", 0), _serve(NOISY))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = "http://127.0.0.1:%d/" % srv.server_address[1]
    from invisible_playwright import InvisiblePlaywright
    try:
        with InvisiblePlaywright(seed=42, binary_path=firefox_binary,
                                 headless=True) as browser:
            page = browser.new_page()
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(url)
            page.click("#boom")
            page.wait_for_timeout(600)
            assert errors, "the uncaught error never arrived"
            assert "undefinedFunctionCall" in " ".join(errors), (
                "the message was lost: %s" % errors)
    finally:
        os.environ.pop(factory.CHOICE_ENV, None)
        srv.shutdown()


@pytest.mark.e2e
def test_a_dialog_can_be_ANSWERED_and_not_answering_hangs_the_page(
        firefox_binary):
    """⛔ THE ONE OBJECT WHERE FORGETTING IS A HANG, NOT A LEAK. A dialog
    blocks the content process inside `window.alert`, so an unanswered one
    makes every later command time out with no hint about the cause.

    Playwright's client answers automatically when nobody is listening, and
    that safety net only works if the event ARRIVES - which is what this
    asserts. The second half then checks the explicit path.
    """
    os.environ[factory.CHOICE_ENV] = factory.JUGGLER
    srv = socketserver.TCPServer(("127.0.0.1", 0), _serve(NOISY))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = "http://127.0.0.1:%d/" % srv.server_address[1]
    from invisible_playwright import InvisiblePlaywright
    try:
        with InvisiblePlaywright(seed=42, binary_path=firefox_binary,
                                 headless=True) as browser:
            page = browser.new_page()
            seen = []

            def answer(dialog):
                seen.append((dialog.type, dialog.message))
                dialog.accept()

            page.on("dialog", answer)
            page.goto(url)
            page.click("#alert")
            page.wait_for_timeout(600)
            assert seen == [("alert", "are you sure")], seen
            # And the page is still alive: if the dialog had not been
            # answered, this would time out instead of returning.
            assert page.title() == "events"
    finally:
        os.environ.pop(factory.CHOICE_ENV, None)
        srv.shutdown()


@pytest.mark.e2e
def test_an_unanswered_dialog_is_dismissed_by_the_client(firefox_binary):
    """⛔ The known-bad of the wiring above: with NO listener the client
    dismisses on its own, and the page keeps running. If the event never
    reached the client, this would hang - so a green here proves the event
    arrives even when nobody visibly consumes it."""
    os.environ[factory.CHOICE_ENV] = factory.JUGGLER
    srv = socketserver.TCPServer(("127.0.0.1", 0), _serve(NOISY))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = "http://127.0.0.1:%d/" % srv.server_address[1]
    from invisible_playwright import InvisiblePlaywright
    try:
        with InvisiblePlaywright(seed=42, binary_path=firefox_binary,
                                 headless=True) as browser:
            page = browser.new_page()
            page.goto(url)
            page.click("#alert")
            assert page.title() == "events", (
                "the page is stuck: the dialog event never reached the client")
    finally:
        os.environ.pop(factory.CHOICE_ENV, None)
        srv.shutdown()


# ── context and page surfaces ───────────────────────────────────────────────

def test_a_cookie_domain_with_a_LEADING_DOT_matches_subdomains():
    """⛔ A leading dot means "and every subdomain". Comparing the two strings
    directly is the version that looks right and returns an empty list, so
    `context.cookies(urls=[...])` would answer nothing for a site-wide
    cookie."""
    from invisible_playwright._juggler.server import _domain_matches, _host_of
    assert _host_of("https://shop.example.com:8443/a/b") == "shop.example.com"
    assert _domain_matches(".example.com", "shop.example.com")
    assert _domain_matches("example.com", "example.com")
    assert not _domain_matches(".example.com", "notexample.com"), (
        "a suffix match without the dot boundary: badexample.com would pass")
    assert not _domain_matches("", "example.com")


def test_clearing_cookies_with_a_FILTER_is_refused_not_widened():
    """⛔ The engine command clears the WHOLE context and takes no filter.
    Honouring a filtered request by clearing everything is worse than
    refusing: the caller asked to remove one cookie and would lose the
    session."""
    from invisible_playwright._juggler.dispatcher import ProtocolException
    from invisible_playwright._juggler.server import BrowserContextDispatcher
    method = BrowserContextDispatcher.op_clear_cookies
    with pytest.raises(ProtocolException) as failure:
        method(object(), {"name": "session"})
    assert "whole context" in str(failure.value)


@pytest.mark.e2e
def test_cookies_round_trip_through_the_public_API(firefox_binary):
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
            context = page.context
            context.add_cookies([{"name": "a", "value": "1",
                                  "domain": "127.0.0.1", "path": "/"}])
            names = {c["name"]: c["value"] for c in context.cookies()}
            assert names.get("a") == "1", names
            context.clear_cookies()
            assert not [c for c in context.cookies() if c["name"] == "a"]
    finally:
        os.environ.pop(factory.CHOICE_ENV, None)
        srv.shutdown()


@pytest.mark.e2e
def test_a_screenshot_comes_back_as_real_png_bytes(firefox_binary):
    """⛔ THE MAGIC NUMBER, not the length. A screenshot that is the string
    "None" or a base64 blob nobody decoded is still bytes and still non-empty:
    the only assertion that separates a real image from a plausible one is the
    PNG signature."""
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
            shot = page.screenshot()
            assert shot[:8] == b"\x89PNG\r\n\x1a\n", (
                "not a PNG: first bytes are %r" % shot[:12])
            assert len(shot) > 1000, len(shot)
    finally:
        os.environ.pop(factory.CHOICE_ENV, None)
        srv.shutdown()


@pytest.mark.e2e
def test_the_viewport_can_be_resized(firefox_binary):
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
            page.set_viewport_size({"width": 640, "height": 480})
            assert page.evaluate("() => window.innerWidth") == 640
            assert page.evaluate("() => window.innerHeight") == 480
    finally:
        os.environ.pop(factory.CHOICE_ENV, None)
        srv.shutdown()
