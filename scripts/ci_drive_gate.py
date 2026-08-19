#!/usr/bin/env python3
"""CI drive gate - the firefox-N catcher.

A raw `firefox --screenshot` proves nothing about automation: a juggler-less
binary renders a screenshot just fine and ships broken (firefox-8 did exactly
that). This DRIVES the binary the way users will - Playwright launches it over
the juggler pipe and exercises real paths.

Three levels (see `--click` / `--full`):

  SMOKE (default - run on ALL 5 legs, on every binary's native runner):
    launch over juggler-pipe → navigate a real http://127.0.0.1 page → assert a
    response, the Firefox UA, navigator.webdriver falsy, and a DOM read. This is
    the firefox-8 catcher (a juggler-less binary throws TargetClosedError on
    launch) plus a base stealth + drivability check. It is intentionally LIGHT:
    the free hosted runners - windows-latest especially - are content-process
    unstable under a heavy headless interaction sequence (clicks/moves cascade
    into "context destroyed" / selector-timeout / eval-CSP), so the gate that
    must be GREEN on every leg stays minimal and reliable.

  CLICK (`--click` - run on every leg that is not FULL):
    SMOKE plus ONE mouse move and ONE click, asserting both reached the page.
    Nothing else. It exists because the FULL level below could not run there,
    and that left the mouse untested on the only platforms where it can break.

    ⛔ THE SENTENCE THIS REPLACES WAS WRONG, AND A REAL DEFECT PROVED IT.
    It read: "the interaction code is platform-identical JS (it lives in
    omni.ja), so exercising it on one reliable leg catches a regression for ALL
    platforms". Measured 2026-08-19: a build with MOZILLA_OFFICIAL=1 shows the
    terms-of-use PREONBOARDING MODAL, a full-viewport chrome overlay that
    swallows every mouse event - focus stays on BODY, zero mousedown, zero
    mousemove - while the keyboard keeps working. `browser/app/profile/firefox.js`
    disables preonboarding under `#ifdef XP_LINUX`, so **Linux is immune**: the
    one leg that tested the mouse was the one leg that could not see it. All
    five legs would have been green on a binary whose mouse was dead on Windows
    and macOS, which is the target platform.

    Kept LIGHT on purpose: the flakiness that made FULL Linux-only came from a
    heavy interaction sequence, not from a single click. One move plus one click
    is enough for this defect class - it produces zero events, not wrong ones.

  FULL (`--full` - run on the historically-reliable Linux leg):
    CLICK plus keyboard input (firefox-2 / issue #9:
    jugglerSendMouseEvent/synthesizeMouseEvent), canvas determinism (stealth
    seed must be per-session), and navigator-surface tells.

NOT covered here: WebGL determinism (needs SWGL, false-fails headless) and the
faithful cross-origin iframe test (issue #20) - both live in the local realness
gate. All checks here are headless, no screenshot (GPU-free), loopback-only
(no external network / proxy / secrets) → safe in public CI.

Robustness: a real loopback HTTP page (NOT data: / about:blank - those get
re-normalized / carry an eval-blocking CSP), arrow-function evaluates (never
eval'd), and up to 2 retries on transient context-destroyed/detached/timeout.
A genuinely broken binary fails ALL attempts → the gate fails.

Usage:  python ci_drive_gate.py <firefox-binary> [--click | --full]
Exit 0 + "DRIVE GATE OK ..." on success; non-zero with a reason on failure.
"""
from __future__ import annotations

import http.server
import socketserver
import sys
import threading

HTML = (
    "<!doctype html><html><head><title>dt</title></head><body>"
    "<h1 id=x>hello-drive</h1>"
    "<button id=b>go</button>"
    "<input id=inp>"
    "<script>"
    "window.__clicked=0;window.__moves=0;"
    "document.getElementById('b').addEventListener('click',function(){window.__clicked=1;});"
    "window.addEventListener('mousemove',function(){window.__moves++;});"
    "</script>"
    "</body></html>"
).encode()

CANVAS_DRAW = (
    "() => {const c=document.createElement('canvas');c.width=c.height=16;"
    "const g=c.getContext('2d');g.fillStyle='#08f';g.fillRect(0,0,16,16);"
    "g.fillStyle='#f40';g.fillText('s',2,12);return c.toDataURL();}"
)

_TRANSIENT = ("context was destroyed", "frame was detached", "target closed",
              "because of a navigation", "timeout", "blocked by csp")


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(HTML)))
        self.end_headers()
        self.wfile.write(HTML)

    def log_message(self, *a):  # silence per-request stderr noise
        pass


def _start_server():
    srv = socketserver.TCPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


# FF150 + Fission auto-loads about:newtab (TopSitesFeed) ~100ms-1s after a tab's
# first navigation - a cross-process BC swap that REPLACES the page out from under
# the test. The wrapper always disables it (see prefs.py); raw Playwright does not,
# so the binary's realistic config must set it here too. Without this the drive page
# can vanish mid-sequence (it loses the race whenever an action adds latency, e.g.
# the human-cursor path), surfacing as a phantom "waiting for locator" timeout that
# is an environment artifact, not a binary defect.
_REALISTIC_PREFS = {
    "browser.startup.page": 0,
    "browser.newtabpage.enabled": False,
    "browser.newtab.preload": False,
    "browser.newtabpage.activity-stream.feeds.topsites": False,
    "browser.newtabpage.activity-stream.feeds.section.topstories": False,
    "browser.newtabpage.activity-stream.enabled": False,
}


def _drive(exe: str, url: str, livello: str) -> str:
    """Un giro. `livello` e' "smoke", "click" o "full". Torna la UA."""
    interagisce = livello in ("click", "full")
    full = livello == "full"
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.firefox.launch(executable_path=exe, headless=True,
                                   firefox_user_prefs=_REALISTIC_PREFS)
        try:
            page = browser.new_page()
            resp = page.goto(url, wait_until="load")
            assert resp and resp.ok, f"navigation to {url} failed: {resp.status if resp else 'no response'}"
            ua = page.evaluate("() => navigator.userAgent")
            webdriver = page.evaluate("() => navigator.webdriver")
            text = page.evaluate("() => document.getElementById('x').textContent")

            inter = {}
            if interagisce:
                # firefox-2 / issue-#9 catcher: real mouse over juggler.
                page.wait_for_selector("#b")
                page.mouse.move(20, 20)
                page.mouse.move(120, 90)          # synthesizeMouseEvent path
                page.click("#b")                  # mousedown/up/click → listener fires
                inter["clicked"] = page.evaluate("() => window.__clicked")
                inter["moves"] = page.evaluate("() => window.__moves")
            if full:
                page.click("#inp")
                page.keyboard.type("ok")
                inter["typed"] = page.evaluate("() => document.getElementById('inp').value")
                inter["canvas_a"] = page.evaluate(CANVAS_DRAW)
                inter["canvas_b"] = page.evaluate(CANVAS_DRAW)
                inter["langs"] = page.evaluate("() => navigator.languages.length")
                inter["plugins"] = page.evaluate("() => navigator.plugins instanceof PluginArray")
        finally:
            browser.close()

    # SMOKE asserts (always).
    assert "Firefox" in ua, f"unexpected UA (binary not driving correctly): {ua!r}"
    assert text == "hello-drive", f"DOM/JS roundtrip failed: {text!r}"
    assert not webdriver, f"navigator.webdriver leaked True (stealth regression): {webdriver!r}"

    if interagisce:
        assert inter["clicked"] == 1, "page.click() did not fire the click listener - mouse-event synthesis broken (firefox-2 class), or a chrome overlay is swallowing input (terms-of-use modal: see browser/app/profile/firefox.js, termsofuse.acceptedDate)"
        assert inter["moves"] >= 1, "page.mouse.move() produced no mousemove - jugglerSendMouseEvent regression, or a chrome overlay is swallowing input"
    if full:
        assert inter["typed"] == "ok", f"page.keyboard.type() failed: {inter['typed']!r}"
        assert inter["canvas_a"] == inter["canvas_b"], "canvas non-deterministic across identical draws (stealth seed broken → bot tell)"
        assert inter["langs"] and inter["langs"] > 0, "navigator.languages empty (headless tell)"
        assert inter["plugins"], "navigator.plugins is not a PluginArray (headless tell)"
    return ua


def main(exe: str, livello: str) -> int:
    srv, port = _start_server()
    url = f"http://127.0.0.1:{port}/"
    level = livello
    extras = {"full": "http+click+mousemove+keyboard+canvas-determinism+navsurface",
              "click": "http+ua+webdriver+dom+click+mousemove",
              "smoke": "http+ua+webdriver+dom"}[livello]
    last = None
    try:
        for attempt in (1, 2, 3):
            try:
                ua = _drive(exe, url, livello)
                if attempt > 1:
                    print(f"(note: drive succeeded on attempt {attempt} after a transient error)")
                print(f"DRIVE GATE OK [{level}] | UA={ua} | {extras}=ok")
                return 0
            except Exception as e:  # noqa: BLE001 - gate: any failure must surface
                last = e
                msg = str(e).lower()
                if attempt < 3 and any(t in msg for t in _TRANSIENT):
                    print(f"(transient error on attempt {attempt}, retrying): {e}", file=sys.stderr)
                    continue
                break
    finally:
        srv.shutdown()
    print(f"DRIVE GATE FAILED [{level}]: {last}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    args = sys.argv[1:]
    livello = "full" if "--full" in args else ("click" if "--click" in args else "smoke")
    positional = [a for a in args if not a.startswith("--")]
    if len(positional) != 1:
        print("usage: ci_drive_gate.py <path-to-firefox-binary> [--click | --full]", file=sys.stderr)
        sys.exit(2)
    sys.exit(main(positional[0], livello))
