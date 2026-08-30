"""The file-chooser dialog gets intercepted, and the NATIVE one never opens.

WHY THIS GATE EXISTS. This is the most silent failure class the project has
seen: the whole JS/Juggler chain existed and was wired up correctly - the
`Page.setInterceptFileChooserDialog` command, the `Page.fileChooserOpened`
event, the flag on the docShell, the observer in PageAgent.js - but the last
native link was MISSING. The flag was written and nobody read it (the comment
in `nsDocShell.cpp` said so: "storage only"), and the observer PageAgent was
listening for, `juggler-file-picker-shown`, appeared in the whole tree only on
the line that listened for it: nobody ever fired it.

The result: `expect_file_chooser()` hung until timeout while a real Windows
"Open File" window actually popped open, stealing focus from the operating
system - while the package's public docs promise in writing the opposite
("The native OS window never appears on screen"). No test in the suite
covered it: the only ones that touch it are Microsoft's upstream tests, which
live in `tests/playwright-upstream/`, a folder excluded from pytest.

⛔ THE THIRD TEST IS THE CONTROL AND MUST NOT BE REMOVED. Suppressing the
native dialog is easy; suppressing it ONLY when automation asked for it is the
point. Without the control, this file would stay green even if we had broken
file inputs for everyone - which is exactly how a defect gets "fixed" by
making the product worse.
"""
from __future__ import annotations

import http.server
import socketserver
import threading

import pytest

from invisible_playwright import InvisiblePlaywright

PAGINA = b"""<!DOCTYPE html><html><body>
<input id="f" type="file">
<button id="b" onclick="document.getElementById('f').click()">carica</button>
<pre id="out"></pre>
<script>
document.getElementById('f').addEventListener('change', (e) => {
  const n = e.target.files.length ? e.target.files[0].name : '(nessuno)';
  document.getElementById('out').textContent = 'change:' + n;
});
</script></body></html>"""


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(PAGINA)))
        self.end_headers()
        self.wfile.write(PAGINA)

    def log_message(self, *a):
        pass


@pytest.fixture
def pagina_locale():
    """A real page from 127.0.0.1: `data:` URLs carry their own CSP."""
    with socketserver.TCPServer(("127.0.0.1", 0), _Handler) as srv:
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            yield "http://127.0.0.1:%d" % srv.server_address[1]
        finally:
            srv.shutdown()


@pytest.fixture
def file_campione(tmp_path):
    p = tmp_path / "campione.txt"
    p.write_bytes(b"contenuto di prova")
    return str(p)


@pytest.mark.e2e
def test_expect_file_chooser_receives_the_event(firefox_binary, pagina_locale):
    """The event arrives. Before 2026-08-25 this always timed out.

    ⛔ There used to be an `xfail` here, and it went away as it promised to. Its
    reason said: the fix lives in the ENGINE (PageAgent.js listens for
    `file-input-picker-opening` instead of `juggler-file-picker-shown`) as of a
    commit AFTER `firefox-20`, "turns green on its own at the first firefox-N
    that includes that commit". That release is `firefox-21`: measured on
    2026-08-27 against the SHIPPED binary (BuildID 20260827000135, the same one
    the seal declares), this case now comes back XPASS.

    The other two tests in this file remain `xfail`: they are [B178], which
    this release does not touch - verified that no commit between
    `firefox-20` and HEAD names `setFileInputFiles`.
    """
    with InvisiblePlaywright(seed=42, binary_path=firefox_binary) as browser:
        page = browser.new_page()
        page.goto(pagina_locale, wait_until="load")
        with page.expect_file_chooser(timeout=15000) as info:
            page.click("#b")
        chooser = info.value
        # is_multiple is a METHOD on this client, not a property.
        assert chooser.is_multiple() is False
        assert chooser.element is not None


@pytest.mark.xfail(
    reason="PRE-EXISTING defect, not from this patch: setting REAL files on "
           "an input fails (`setFileInputFiles` -> 'object ... no longer "
           "usable', and `set_input_files` times out). Verified on the "
           "binary from the latest release, where it fails identically. See "
           "70-known-bugs.md [B178]. This test turns green on its own the "
           "day B178 is closed, and that is why it was not deleted.",
    strict=False)
@pytest.mark.e2e
def test_the_chosen_files_arrive_at_the_page(firefox_binary, pagina_locale,
                                              file_campione):
    """It is not enough for the event to fire: the file must actually reach the DOM.

    A `change` that does not fire would be a suppressed signal, which per rule
    12 is a FAILURE, not a success.
    """
    with InvisiblePlaywright(seed=42, binary_path=firefox_binary) as browser:
        page = browser.new_page()
        page.goto(pagina_locale, wait_until="load")
        with page.expect_file_chooser(timeout=15000) as info:
            page.click("#b")
        info.value.set_files(file_campione)
        page.wait_for_timeout(400)
        assert "campione.txt" in page.inner_text("#out")


@pytest.mark.xfail(
    reason="same PRE-EXISTING defect as B178: `set_input_files` with a "
           "real path times out even on the binary from the latest "
           "release. Stays here because it IS THE CONTROL - the day B178 "
           "is closed it must go back to proving that the dialog is "
           "suppressed ONLY on request - but it cannot be a hard assertion "
           "while the API it uses is broken upstream.",
    strict=False)
@pytest.mark.e2e
def test_without_interception_the_file_inputs_remain_normal(firefox_binary,
                                                              pagina_locale,
                                                              file_campione):
    """THE CONTROL. The fix must suppress the dialog ONLY on request.

    Here nobody asks to intercept: `set_input_files` must keep working and
    the page must see its `change`. If this turns red, the fix broke file
    inputs for everyone instead of intercepting them just for us.
    """
    with InvisiblePlaywright(seed=42, binary_path=firefox_binary) as browser:
        page = browser.new_page()
        page.goto(pagina_locale, wait_until="load")
        page.set_input_files("#f", file_campione)
        page.wait_for_timeout(300)
        assert "campione.txt" in page.inner_text("#out")
