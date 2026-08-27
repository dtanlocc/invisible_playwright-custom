"""The injected script, called from Python.

⛔ THIS MODULE REIMPLEMENTS NOTHING, and the reason is that it could not:
selector engines and actionability work on the DOM, and Python is not in
the page. JavaScript stays JavaScript; this file only handles loading it
into the right world and calling it.

THE TWO WORLDS, which are the reason for this entire file. Firefox gives
automation a separate context that sees the same DOM **through an Xray**:
inside it `addEventListener`, `textContent` and `querySelector` are the
NATIVE ones, not the ones the site may have replaced. In the MAIN world
everything belongs to the site, and every read is accountable to whoever
wrapped the accessor. On 2026-08-27 two spots that used the wrong world
produced 13 listeners plus one `textContent` read for every
`bounding_box()`: see `31-client-fork.md` §3.9 and §3.10.

**Rule: this file ALWAYS works in the utility world.**

HOW IT IS CREATED. There is no "create a world" command: you send
`Page.setInitScripts` with an **empty** script and a `worldName`, and
Juggler announces the context with `Runtime.executionContextCreated`,
whose `auxData.name` carries that name. ⛔ The name is `__ctx_aux__` and
**is not the upstream one**: our fork renamed it because it used to
travel on the page's window (`31-client-fork.md` §3.5). Changing it here
without changing it there breaks the hookup silently.
"""
from __future__ import annotations

import json
import pathlib
import time
from typing import Any, Optional

#: ⛔ Must stay equal to the driver's `UTILITY_WORLD_NAME` and to the name
#: that `31-client-fork.md` §3.5 declares. This is not a cosmetic detail:
#: it is the key that identifies the right context in
#: `executionContextCreated`.
UTILITY_WORLD = "__ctx_aux__"

_SOURCE = pathlib.Path(__file__).with_name("injected.js")


class EvaluationError(RuntimeError):
    """The JavaScript raised. Carries the PAGE's text and stack."""


class InjectedScript:
    """One `InjectedScript` per frame, in the utility world."""

    def __init__(self, connection, session: str):
        self.c = connection
        self.session = session
        #: (frameId, worldName) -> executionContextId
        self.contexts: dict = {}
        #: frameId -> objectId of the InjectedScript
        self._handle: dict = {}
        previous = connection.on_event

        def route(method, params, event_session):
            if event_session == self.session:
                self._on_event(method, params)
            previous(method, params, event_session)

        connection.on_event = route

    def _on_event(self, method: str, p: dict) -> None:
        if method == "Runtime.executionContextCreated":
            aux = p.get("auxData") or {}
            self.contexts[(aux.get("frameId"), aux.get("name") or "")] = \
                p["executionContextId"]
        elif method == "Runtime.executionContextDestroyed":
            dead = p["executionContextId"]
            for k in [k for k, v in self.contexts.items() if v == dead]:
                self.contexts.pop(k, None)
            # ⛔ And the handle is discarded: an objectId of a destroyed
            # context does not fail right away, it gives WRONG results.
            # The document changed underneath, so the injected script
            # must be rebuilt.
            for f in [f for f, _ in list(self._handle.items())
                      if (f, UTILITY_WORLD) not in self.contexts]:
                self._handle.pop(f, None)

    # ── the world ───────────────────────────────────────────────────────────
    def install(self) -> None:
        """Creates the utility world. An EMPTY script is enough: what
        matters is the `worldName`, which is the only thing that makes
        the context come into being."""
        self.c.send("Page.setInitScripts",
                    {"scripts": [{"script": "", "worldName": UTILITY_WORLD}]},
                    session=self.session)

    def context_id(self, frame_id: str, *, timeout: float = 10.0) -> str:
        key = (frame_id, UTILITY_WORLD)
        deadline = time.monotonic() + timeout
        while key not in self.contexts:
            if time.monotonic() > deadline:
                worlds = sorted(n for f, n in self.contexts if f == frame_id)
                raise TimeoutError(
                    "the utility world (%s) has not been born for frame "
                    "%s in %.0fs. Worlds seen for that frame: %s. Did "
                    "you call install()?" % (UTILITY_WORLD, frame_id,
                                             timeout, worlds or "none"))
            time.sleep(0.01)
        return self.contexts[key]

    # ── evaluation ──────────────────────────────────────────────────────────
    def _result(self, response: dict) -> dict:
        """⛔ An exception from the page does NOT arrive as a protocol
        error: it arrives as an `exceptionDetails` field inside a
        SUCCESSFUL response. Whoever only looks at the return code reads
        `None` and moves on."""
        exc = (response or {}).get("exceptionDetails")
        if exc:
            raise EvaluationError(
                "%s%s" % (exc.get("text") or exc.get("value") or "exception",
                          ("\n" + exc["stack"]) if exc.get("stack") else ""))
        return (response or {}).get("result") or {}

    def evaluate(self, frame_id: str, expression: str, *,
                by_value: bool = True, timeout: float = 30.0) -> Any:
        r = self._result(self.c.send(
            "Runtime.evaluate",
            {"executionContextId": self.context_id(frame_id),
             "expression": expression, "returnByValue": by_value},
            session=self.session, timeout=timeout))
        return r.get("value") if by_value else r.get("objectId")

    def call(self, frame_id: str, declaration: str, *arguments,
             by_value: bool = True, timeout: float = 30.0) -> Any:
        """`declaration` is a JS declaration; the FIRST argument passed
        is always the InjectedScript, the way the driver does it."""
        args = [{"objectId": self.handle(frame_id)}]
        for a in arguments:
            args.append(a if isinstance(a, dict) and
                        ("objectId" in a or "value" in a) else {"value": a})
        r = self._result(self.c.send(
            "Runtime.callFunction",
            {"executionContextId": self.context_id(frame_id),
             "functionDeclaration": declaration, "args": args,
             "returnByValue": by_value},
            session=self.session, timeout=timeout))
        return r.get("value") if by_value else r.get("objectId")

    def handle(self, frame_id: str) -> str:
        """The frame's InjectedScript, built only once."""
        if frame_id in self._handle:
            return self._handle[frame_id]
        options = {
            # ⛔ `isUnderTest` FALSE, always. If true, the InjectedScript
            # plants `window.builtins` and `window.__injectedScript` on
            # the page's window, ENUMERABLE: it is the tell that
            # `31-client-fork.md` §3.3 declares turned off, and turning
            # it back on from here would restore it.
            "isUnderTest": False,
            "sdkLanguage": "python",
            "testIdAttributeName": "data-testid",
            "stableRafCount": 1,
            "browserName": "firefox",
            "shouldPrependErrorPrefix": False,
            # ⛔ TRUE, and this is the line that keeps the 13 listeners
            # out: with false the constructor installs them on the
            # PAGE's addEventListener.
            "isUtilityWorld": True,
            "customEngines": [],
        }
        source = _SOURCE.read_text(encoding="utf-8")
        expression = ("(() => { const module = {};\n%s\n"
                      "return new (module.exports.InjectedScript())"
                      "(globalThis, %s); })();"
                      % (source, json.dumps(options)))
        oid = self.evaluate(frame_id, expression, by_value=False)
        if not oid:
            raise EvaluationError(
                "the InjectedScript did not return an object: "
                "is the source the right one?")
        self._handle[frame_id] = oid
        return oid

    # ── the little needed on top ────────────────────────────────────────────
    def query_selector(self, frame_id: str, selector: str,
                       *, strict: bool = False) -> Optional[str]:
        """The objectId of the first matching element, or None."""
        return self.call(
            frame_id,
            "(injected, sel, strict) => {"
            "  const p = injected.parseSelector(sel);"
            "  return injected.querySelector(p, document, strict) || null; }",
            selector, strict, by_value=False)

    def count(self, frame_id: str, selector: str) -> int:
        return self.call(
            frame_id,
            "(injected, sel) => injected.querySelectorAll("
            "injected.parseSelector(sel), document).length",
            selector)

    def element_states(self, frame_id: str, element: str,
                       states: list) -> dict:
        """Asks the injected script whether the element is actionable.

        Returns `{"ok": True}` or `{"ok": False, "missing": "<state>"}`.
        The states are Playwright's: `visible`, `stable`, `enabled`,
        `editable`. ⛔ `stable` is ASYNCHRONOUS (it waits two frames), so
        the function is `async` and the value must be awaited: without
        `await` you would get a Promise and every element would come out
        actionable.
        """
        return self.call(
            frame_id,
            "async (injected, el, states) => {"
            "  const r = await injected.checkElementStates(el, states);"
            "  if (r === undefined) return { ok: true };"
            "  if (typeof r === 'string') return { ok: false, missing: r };"
            "  return { ok: false, missing: r.missingState }; }",
            {"objectId": element}, states)

    def text_content(self, frame_id: str, element: str) -> str:
        """⛔ Goes through the utility world, hence through the Xray: the
        same read done in the MAIN world would be accountable to the
        site."""
        return self.call(
            frame_id,
            "(injected, el) => el.textContent || ''",
            {"objectId": element})

    # ── the "DOM read" group from item 6 (§6.5) ─────────────────────────────
    #
    # ⛔ Every read goes through the UTILITY world, hence through the
    # Xray. The same lines run in the MAIN world would be accountable to
    # a site that wrapped the accessor, and that is the defect measured
    # in §3.9 and §3.10 of `31-client-fork.md`.

    #: The states that `injected.elementState` actually knows, read from
    #: its code and not assumed. Asking for one outside this set
    #: silently returns a value that means nothing.
    KNOWN_STATES = ("visible", "hidden", "enabled", "disabled", "editable",
                    "checked", "unchecked", "indeterminate")

    def element_state(self, frame_id: str, element: str, state: str) -> bool:
        """`is_visible`, `is_enabled`, `is_checked` and their siblings."""
        if state not in self.KNOWN_STATES:
            raise ValueError("unknown state: %r (the real ones are %s)"
                             % (state, ", ".join(self.KNOWN_STATES)))
        r = self.call(
            frame_id,
            "(injected, el, s) => injected.elementState(el, s)",
            {"objectId": element}, state)
        # ⛔ `elementState` does NOT return a boolean: it returns
        # `{matches, received}`, and on a detached node `received` is
        # `error:notconnected`. Reading it as a boolean would give
        # `True` for a non-empty dict, i.e. ALWAYS.
        if isinstance(r, dict):
            if isinstance(r.get("received"), str) and \
                    r["received"].startswith("error:"):
                raise EvaluationError(
                    "elementState(%s): %s" % (state, r["received"]))
            return bool(r.get("matches"))
        return bool(r)

    def inner_text(self, frame_id: str, element: str) -> str:
        return self.call(frame_id, "(injected, el) => el.innerText",
                         {"objectId": element})

    def inner_html(self, frame_id: str, element: str) -> str:
        return self.call(frame_id, "(injected, el) => el.innerHTML",
                         {"objectId": element})

    def input_value(self, frame_id: str, element: str) -> str:
        """`input_value`. ⛔ Only valid on input, textarea and select: on
        a div it would silently return `undefined`, so it REFUSES
        instead."""
        return self.call(
            frame_id,
            "(injected, el) => {"
            "  const e = injected.retarget(el, 'follow-label');"
            "  const n = e && e.nodeName.toLowerCase();"
            "  if (n !== 'input' && n !== 'textarea' && n !== 'select')"
            "    throw new Error('Node is not an <input>, <textarea> or <select> element');"
            "  return e.value; }",
            {"objectId": element})

    def get_attribute(self, frame_id: str, element: str, name: str):
        """⛔ An ABSENT attribute must return `None`, not the empty
        string: `getAttribute` already returns `null` on its own, but an
        empty value and an absence are two different things and the
        reader must be able to tell them apart."""
        return self.call(
            frame_id, "(injected, el, n) => el.getAttribute(n)",
            {"objectId": element}, name)

    def title(self, frame_id: str) -> str:
        return self.evaluate(frame_id, "document.title")

    def content(self, frame_id: str) -> str:
        """`page.content()`.

        ⛔ Serializes with `outerHTML`, so it does NOT enter any shadow
        root, not even an open one. This is a known limitation of the
        product: do not promise otherwise.
        """
        return self.evaluate(
            frame_id,
            "(document.doctype ? new XMLSerializer()"
            ".serializeToString(document.doctype) : '')"
            " + (document.documentElement ? document.documentElement.outerHTML : '')")

    def bounding_box(self, frame_id: str, element: str):
        """`bounding_box`: x, y, width, height from the quads, or None.

        ⛔ Goes through `Page.getContentQuads` and NOT through the
        page's `getBoundingClientRect`: that getter belongs to the
        site, and reading it would be accountable.
        """
        r = self.c.send("Page.getContentQuads",
                        {"frameId": frame_id, "objectId": element},
                        session=self.session, timeout=10) or {}
        quads = r.get("quads") or []
        if not quads:
            return None
        points = [p for q in quads
                  for p in (q["p1"], q["p2"], q["p3"], q["p4"])]
        x1 = min(p["x"] for p in points)
        y1 = min(p["y"] for p in points)
        x2 = max(p["x"] for p in points)
        y2 = max(p["y"] for p in points)
        return {"x": x1, "y": y1, "width": x2 - x1, "height": y2 - y1}

    def dispose(self, frame_id: str, element: str) -> None:
        """A retained objectId keeps a page DOM node alive.

        ⛔ `Runtime.disposeObject` ALSO wants the `executionContextId`:
        an objectId alone identifies nothing, because the same number
        can exist in two contexts.
        """
        try:
            self.c.send("Runtime.disposeObject",
                        {"executionContextId": self.context_id(frame_id),
                         "objectId": element},
                        session=self.session, timeout=5)
        except Exception:
            pass
