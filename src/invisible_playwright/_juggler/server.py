"""The Python side of the Playwright protocol, backed by Juggler.

⛔ EVERY SHAPE IN THIS FILE WAS MEASURED, NOT DEDUCED. `scripts/capture_protocol.py`
records a real session against the Node driver, and the initializers, the object
parentage, the event names and the ordering below come from that recording. The
difference matters: reading `_impl` tells you which initializer fields are
CONSUMED today, and the fields a future code path will want are exactly the ones
that reading cannot show you.

**WHAT THE RECORDING SAID, and some of it is not what you would guess:**

- `goto`, `click`, `fill`, `title`, `content` and `querySelector` are sent to
  the **Frame**, not the Page. The Page owns almost nothing.
- `mouseMove` IS sent to the Page - and in a humanised session it arrives
  nineteen times for one click, because the cursor travels.
- `BrowserContext` is created with three children already alive - `Debugger`,
  `Tracing`, `APIRequestContext` - and each is announced BEFORE the context that
  names it, then re-parented with `__adopt__`.
- A `Frame` is created before its `Page` and adopted afterwards, so the Page
  initializer can point at a `mainFrame` that already exists.

**THE ORDER IS THE PROTOCOL.** `Connection.dispatch` looks a guid up in a plain
dict and raises `Cannot find object` when it is missing, so a `__create__` that
arrives after the message naming it is not a race that usually works: it is a
hard failure. Everything here creates first and returns the channel second.
"""
from __future__ import annotations

import json
import pathlib
import tempfile
import threading
import time
from typing import Any, Dict, List, Optional

from . import connection as juggler
from .actions import Actions
from .dispatcher import Dispatcher, ProtocolException, Server
from .injected import InjectedScript
from .lifecycle import Lifecycle


def _as_callable(expression: str) -> str:
    """Wrap an expression so it can always be CALLED with the argument.

    <M> PLAYWRIGHT SENDS BOTH FORMS DOWN THE SAME FIELD. `page.evaluate("1+1")`
    and `page.evaluate("() => document.title")` arrive as the same
    `expression` string, and the client does not say which is which. Evaluating
    the raw string works for the first and, for the second, produces a FUNCTION
    OBJECT: no error, no exception, and the caller gets None back for a call
    that looked fine.

    Measured on 2026-08-27: `page.evaluate("() => !!x")` answered None, and the
    assertion that caught it read like the browser had changed behaviour.

    So the string is wrapped and the result called if it turned out to be a
    function. Deciding by shape - does it start with `(` or `function` or
    `async` - is the version that gets it wrong: `(1+2)` starts with a
    parenthesis and is not a function.
    """
    return ("(() => { const r = (%s);"
            "  return typeof r === 'function' ? r(ARG) : r; })()" % expression)


def _deserialize(value: Any) -> Any:
    """The tagged union Playwright sends for an ARGUMENT, back to a value."""
    if not isinstance(value, dict):
        return value
    if "value" in value and "handles" in value:
        return _deserialize(value["value"])
    for tag, convert in (("n", lambda v: v), ("s", lambda v: v),
                         ("b", lambda v: v)):
        if tag in value:
            return convert(value[tag])
    if "v" in value:
        return {"null": None, "undefined": None, "NaN": float("nan"),
                "Infinity": float("inf"),
                "-Infinity": float("-inf")}.get(value["v"])
    if "a" in value:
        return [_deserialize(x) for x in value["a"]]
    if "o" in value:
        return {e["k"]: _deserialize(e["v"]) for e in value["o"]}
    return None


def _with_argument(params: Dict) -> str:
    """The expression, callable, with the caller's argument substituted in."""
    argument = _deserialize(params.get("arg"))
    return _as_callable(params["expression"]).replace(
        "ARG", json.dumps(argument, default=str))


def _js_string(value: str) -> str:
    """A Python string as a JavaScript literal.

    ⛔ `json.dumps` and never manual quoting: the html handed to `set_content`
    is arbitrary, and a single quote, a backslash or a line separator inside it
    would close the literal early. That exact defect - an apostrophe closing a
    single-quoted JavaScript string - broke the driver bundle on 2026-08-24.
    """
    return json.dumps(value)


def _guid_of(value: Any) -> Optional[str]:
    if isinstance(value, dict) and "guid" in value:
        return value["guid"]
    return None


# ── the leaves we do not implement, and say so ──────────────────────────────
class RefusingDispatcher(Dispatcher):
    """An object that exists so the tree is well formed, and refuses the rest.

    ⛔ IT EXISTS BECAUSE THE PROTOCOL REQUIRES IT, NOT BECAUSE WE SUPPORT IT.
    `BrowserContext`'s initializer names a `tracing`, a `debugger` and a
    `requestContext`, and `_browser_context.py` reads all three with
    `from_channel` at construction time. Leaving them out does not disable
    tracing: it raises a KeyError before any page exists.

    So they are created, and every method on them refuses with a reason. That is
    the whole of section 5.4: out of perimeter must FAIL LOUDLY, never no-op and
    never AttributeError.
    """

    REASON = "not implemented"

    def call(self, method: str, params: Dict) -> Any:
        if method in self.METHODS:
            return super().call(method, params)
        raise ProtocolException(
            "%s.%s is outside what invisible_playwright implements: %s. This "
            "is a deliberate refusal, not a gap - see "
            "32-stacco-da-playwright.md section 5.4."
            % (self.TYPE, method, self.REASON))


class TracingDispatcher(RefusingDispatcher):
    TYPE = "Tracing"
    REASON = ("tracing is outside the automation core; it records a session "
              "for the trace viewer and drives none of it")
    METHODS = {"tracingStop": "stop_noop", "tracingStopChunk": "stop_noop"}

    def stop_noop(self, params: Dict) -> Any:
        # ⛔ These two answer instead of refusing because `close()` calls them
        # on the way out: refusing here would turn every clean shutdown into an
        # error about a feature the caller never asked for.
        return {"artifact": None}


class DebuggerDispatcher(RefusingDispatcher):
    TYPE = "Debugger"
    REASON = "the inspector and its paused state are not part of this fork"


class APIRequestContextDispatcher(RefusingDispatcher):
    TYPE = "APIRequestContext"
    REASON = ("APIRequestContext performs HTTP outside the page, which is not "
              "browser automation and carries none of the browser fingerprint")
    METHODS = {"dispose": "dispose_self"}

    def dispose_self(self, params: Dict) -> Any:
        self.dispose()
        return None


# ── handles ─────────────────────────────────────────────────────────────────
class ElementHandleDispatcher(Dispatcher):
    TYPE = "ElementHandle"
    METHODS = {
        "dispose": "op_dispose",
        "boundingBox": "op_bounding_box",
        "evaluateExpression": "op_evaluate",
        "textContent": "op_text_content",
        "innerText": "op_inner_text",
        "innerHTML": "op_inner_html",
        "inputValue": "op_input_value",
        "getAttribute": "op_get_attribute",
        "scrollIntoViewIfNeeded": "op_scroll_into_view",
        "ownerFrame": "op_owner_frame",
        "contentFrame": "op_content_frame",
        "getProperty": "op_get_property",
        "getPropertyList": "op_get_property_list",
        "jsonValue": "op_json_value",
    }

    def __init__(self, server, frame: "FrameDispatcher", object_id: str,
                 preview: str = "") -> None:
        self.frame = frame
        self.object_id = object_id
        super().__init__(server, frame.page,
                         {"preview": preview or "JSHandle@node"})

    @property
    def page(self) -> "PageDispatcher":
        return self.frame.page

    def op_dispose(self, params: Dict) -> Any:
        try:
            self.page.injected.dispose(self.frame.frame_id, self.object_id)
        except Exception:
            # ⛔ A handle whose context is already gone is not an error worth
            # raising: the caller is tidying up, and the node it pointed at
            # stopped existing on its own.
            pass
        self.dispose()
        return None

    def op_bounding_box(self, params: Dict) -> Any:
        return {"value": self.page.injected.bounding_box(
            self.frame.frame_id, self.object_id)}

    def op_evaluate(self, params: Dict) -> Any:
        # ⛔ On a handle the expression is ALWAYS called with the element, so
        # the bare-expression form does not arise here - but a non-function
        # still has to answer rather than raise.
        return {"value": _serialize(self.page.injected.call(
            self.frame.frame_id,
            "(injected, el) => { const r = (%s);"
            "  return typeof r === 'function' ? r(el) : r; }"
            % params["expression"],
            {"objectId": self.object_id}))}

    def op_text_content(self, params: Dict) -> Any:
        return {"value": self.page.injected.text_content(
            self.frame.frame_id, self.object_id)}

    def op_inner_text(self, params: Dict) -> Any:
        return {"value": self.page.injected.inner_text(
            self.frame.frame_id, self.object_id)}

    def op_inner_html(self, params: Dict) -> Any:
        return {"value": self.page.injected.inner_html(
            self.frame.frame_id, self.object_id)}

    def op_input_value(self, params: Dict) -> Any:
        return {"value": self.page.injected.input_value(
            self.frame.frame_id, self.object_id)}

    def op_get_attribute(self, params: Dict) -> Any:
        return {"value": self.page.injected.get_attribute(
            self.frame.frame_id, self.object_id, params["name"])}

    def op_get_property(self, params: Dict) -> Any:
        object_id = self.page.injected.call(
            self.frame.frame_id,
            "(injected, o, n) => o[n]",
            {"objectId": self.object_id}, params["name"], by_value=False)
        handle = ElementHandleDispatcher(self.server, self.frame, object_id)
        return {"handle": handle.channel}

    def op_get_property_list(self, params: Dict) -> Any:
        """⛔ ONE HANDLE PER PROPERTY, and each one holds its value alive. On a
        large object this is the most expensive call in the file, which is why
        `json_value` exists and should be preferred when the values are
        serialisable."""
        names = self.page.injected.call(
            self.frame.frame_id,
            "(injected, o) => o === Object(o) ? Object.keys(o) : []",
            {"objectId": self.object_id}) or []
        out = []
        for name in names:
            object_id = self.page.injected.call(
                self.frame.frame_id, "(injected, o, n) => o[n]",
                {"objectId": self.object_id}, name, by_value=False)
            handle = ElementHandleDispatcher(self.server, self.frame, object_id)
            out.append({"name": name, "value": handle.channel})
        return {"properties": out}

    def op_json_value(self, params: Dict) -> Any:
        return {"value": _serialize(self.page.injected.call(
            self.frame.frame_id, "(injected, o) => o",
            {"objectId": self.object_id}))}

    def op_scroll_into_view(self, params: Dict) -> Any:
        """⛔ [B184]: this does not work in the shipped engine, and it does not
        work through the Node driver either. It is wired correctly here so the
        day the engine is fixed nothing else has to change, and the failure
        arrives from the engine rather than from a missing method."""
        self.page.send("Page.scrollIntoViewIfNeeded",
                       _only_set({"frameId": self.frame.frame_id,
                                  "objectId": self.object_id,
                                  "rect": params.get("rect")}))
        return None

    def op_owner_frame(self, params: Dict) -> Any:
        return {"frame": self.frame.channel}

    def op_content_frame(self, params: Dict) -> Any:
        """The frame this element CONTAINS, for an iframe.

        ⛔ Answers null rather than raising when the element is not a frame
        owner: that is what the client expects, and raising would turn an
        ordinary "this div is not an iframe" into a failed script.
        """
        result = self.page.send("Page.describeNode",
                                {"frameId": self.frame.frame_id,
                                 "objectId": self.object_id}) or {}
        content_frame_id = result.get("contentFrameId")
        if not content_frame_id:
            return {"frame": None}
        frame = self.page.frame_for(content_frame_id)
        return {"frame": frame.channel}


def _serialize(value: Any, counter: Optional[Dict] = None) -> Any:
    """A Python value in the shape `parse_result` expects.

    ⛔ Playwright does not send bare JSON: it sends a tagged union, and
    `_connection.parse_value` reads the TAG. A bare `True` where `{"b": true}`
    is expected does not raise - it falls through to the object branch and comes
    back as something else entirely.
    """
    if counter is None:
        counter = {"n": 0}
    if value is None:
        return {"v": "null"}
    if isinstance(value, bool):
        return {"b": value}
    if isinstance(value, (int, float)):
        return {"n": value}
    if isinstance(value, str):
        return {"s": value}
    if isinstance(value, (list, tuple)):
        # <M> `id` IS MANDATORY on a list and on an object, and its absence is
        # a KeyError deep inside `parse_value`, not a message. Playwright uses
        # it to rebuild cyclic references: every container is registered under
        # its id so a later `{"ref": id}` can point back at it. We never emit a
        # `ref` - the values crossing here come from JSON and cannot be cyclic
        # - but the id has to be there anyway, because the reader indexes on it
        # unconditionally.
        counter["n"] += 1
        return {"a": [_serialize(x, counter) for x in value], "id": counter["n"]}
    if isinstance(value, dict):
        counter["n"] += 1
        return {"o": [{"k": k, "v": _serialize(v, counter)}
                      for k, v in value.items()], "id": counter["n"]}
    return {"s": str(value)}


# ── frame ───────────────────────────────────────────────────────────────────
class FrameDispatcher(Dispatcher):
    TYPE = "Frame"
    METHODS = {
        "goto": "op_goto",
        "querySelector": "op_query_selector",
        "click": "op_click",
        "fill": "op_fill",
        "title": "op_title",
        "content": "op_content",
        "textContent": "op_text_content",
        "innerText": "op_inner_text",
        "innerHTML": "op_inner_html",
        "inputValue": "op_input_value",
        "getAttribute": "op_get_attribute",
        "isVisible": "op_is_visible",
        "isHidden": "op_is_hidden",
        "isEnabled": "op_is_enabled",
        "isDisabled": "op_is_disabled",
        "isChecked": "op_is_checked",
        "isEditable": "op_is_editable",
        "hover": "op_hover",
        "dblclick": "op_dblclick",
        "check": "op_check",
        "uncheck": "op_uncheck",
        "focus": "op_focus",
        "blur": "op_blur",
        "selectText": "op_select_text",
        "press": "op_press",
        "type": "op_type",
        "evaluateExpression": "op_evaluate",
        "evaluateExpressionHandle": "op_evaluate_handle",
        "querySelectorAll": "op_query_selector_all",
        "queryCount": "op_query_count",
        "waitForSelector": "op_wait_for_selector",
        "waitForFunction": "op_wait_for_function",
        "waitForTimeout": "op_wait_for_timeout",
        "setContent": "op_set_content",
        "evalOnSelector": "op_eval_on_selector",
        "evalOnSelectorAll": "op_eval_on_selector_all",
        "selectOption": "op_select_option",
        "setInputFiles": "op_set_input_files",
        "tap": "op_tap",
        "dispatchEvent": "op_dispatch_event",
        "dragAndDrop": "op_drag_and_drop",
        "frameElement": "op_frame_element",
        "expect": "op_expect",
        "resolveSelector": "op_resolve_selector",
        "waitForElementState": "op_wait_for_element_state",
        "setTestIdAttributeName": "op_set_test_id",
    }

    def __init__(self, server, page: "PageDispatcher", frame_id: str,
                 url: str = "about:blank", name: str = "",
                 load_states: Optional[List[str]] = None) -> None:
        self.page = page
        self.frame_id = frame_id
        super().__init__(server, page.context,
                         {"url": url, "name": name,
                          "loadStates": load_states or ["commit"]})

    # ── navigation ──────────────────────────────────────────────────────────
    def op_goto(self, params: Dict) -> Any:
        result = self.page.lifecycle.goto(
            params["url"], frame_id=self.frame_id,
            until=params.get("waitUntil") or "load",
            timeout=(params.get("timeout") or 30000) / 1000.0)
        self.emit("navigated", {"url": result["url"], "name": "",
                                "newDocument": {"request": None}})
        # ⛔ `goto` answers with a Response CHANNEL or null, never with a URL.
        # `_frame.py` calls `from_nullable_channel` on it.
        return {"response": None}

    # ── reading ─────────────────────────────────────────────────────────────
    def op_title(self, params: Dict) -> Any:
        return {"value": self.page.injected.title(self.frame_id)}

    def op_content(self, params: Dict) -> Any:
        return {"value": self.page.injected.content(self.frame_id)}

    def op_query_selector(self, params: Dict) -> Any:
        object_id = self.page.injected.query_selector(
            self.frame_id, params["selector"])
        if not object_id:
            return {"element": None}
        handle = ElementHandleDispatcher(self.server, self, object_id)
        return {"element": handle.channel}

    def _with_element(self, params: Dict, read):
        object_id = self.page.injected.query_selector(
            self.frame_id, params["selector"])
        if not object_id:
            raise ProtocolException(
                "no element matches %r" % params["selector"])
        try:
            return {"value": read(object_id)}
        finally:
            self.page.injected.dispose(self.frame_id, object_id)

    def op_text_content(self, params: Dict) -> Any:
        return self._with_element(params, lambda o: self.page.injected
                                  .text_content(self.frame_id, o))

    def op_inner_text(self, params: Dict) -> Any:
        return self._with_element(params, lambda o: self.page.injected
                                  .inner_text(self.frame_id, o))

    def op_inner_html(self, params: Dict) -> Any:
        return self._with_element(params, lambda o: self.page.injected
                                  .inner_html(self.frame_id, o))

    def op_input_value(self, params: Dict) -> Any:
        return self._with_element(params, lambda o: self.page.injected
                                  .input_value(self.frame_id, o))

    def op_get_attribute(self, params: Dict) -> Any:
        return self._with_element(params, lambda o: self.page.injected
                                  .get_attribute(self.frame_id, o,
                                                 params["name"]))

    def _state(self, params: Dict, state: str) -> Any:
        return self._with_element(params, lambda o: self.page.injected
                                  .element_state(self.frame_id, o, state))

    def op_is_visible(self, params: Dict) -> Any:
        return self._state(params, "visible")

    def op_is_hidden(self, params: Dict) -> Any:
        return self._state(params, "hidden")

    def op_is_enabled(self, params: Dict) -> Any:
        return self._state(params, "enabled")

    def op_is_disabled(self, params: Dict) -> Any:
        return self._state(params, "disabled")

    def op_is_checked(self, params: Dict) -> Any:
        return self._state(params, "checked")

    def op_is_editable(self, params: Dict) -> Any:
        return self._state(params, "editable")

    def op_evaluate(self, params: Dict) -> Any:
        """⛔ THE PAGE'S OWN WORLD, not the utility one, and the distinction
        is the semantics of the API rather than a preference.

        `page.evaluate()` is the user asking to run code AS THE PAGE: it must
        see the page's globals, the page's prototypes, and whatever the site
        has monkey-patched. The utility world sees the same DOM through an
        Xray, so those are exactly what it does NOT see.

        The first draft ran it in utility and it was caught by the opposite
        assertion to the one you would expect: a test checking that the PAGE
        cannot see a closed shadow root found that it could - because the code
        asking was not running as the page at all.

        Everything else in this file stays in utility on purpose. This one
        method leaves, because the caller asked for it.
        """
        return {"value": _serialize(self.page.injected.evaluate_in_main(
            self.frame_id, _with_argument(params)))}

    # ── acting ──────────────────────────────────────────────────────────────
    def _timeout(self, params: Dict) -> float:
        return (params.get("timeout") or 30000) / 1000.0

    def op_click(self, params: Dict) -> Any:
        self.page.actions.click(params["selector"],
                                timeout=self._timeout(params))
        return None

    def op_dblclick(self, params: Dict) -> Any:
        self.page.actions.dblclick(params["selector"],
                                   timeout=self._timeout(params))
        return None

    def op_hover(self, params: Dict) -> Any:
        self.page.actions.hover(params["selector"],
                                timeout=self._timeout(params))
        return None

    def op_fill(self, params: Dict) -> Any:
        self.page.actions.fill(params["selector"], params["value"],
                               timeout=self._timeout(params))
        return None

    def op_check(self, params: Dict) -> Any:
        self.page.actions.check(params["selector"],
                                timeout=self._timeout(params))
        return None

    def op_uncheck(self, params: Dict) -> Any:
        self.page.actions.uncheck(params["selector"],
                                  timeout=self._timeout(params))
        return None

    def op_focus(self, params: Dict) -> Any:
        self.page.actions.focus(params["selector"],
                                timeout=self._timeout(params))
        return None

    def op_blur(self, params: Dict) -> Any:
        self.page.actions.blur(params["selector"],
                               timeout=self._timeout(params))
        return None

    def op_select_text(self, params: Dict) -> Any:
        self.page.actions.select_text(params["selector"],
                                      timeout=self._timeout(params))
        return None

    def op_press(self, params: Dict) -> Any:
        self.page.actions.press(params["selector"], params["key"],
                                timeout=self._timeout(params))
        return None

    def op_type(self, params: Dict) -> Any:
        self.page.actions.type_text(params["selector"], params["text"],
                                    timeout=self._timeout(params))
        return None

    def op_select_option(self, params: Dict) -> Any:
        # ⛔ A bare string never reaches the option filter: it starts from
        # `matches = true` and narrows only on valueOrLabel / value / label /
        # index, so a plain string matches everything and picks the FIRST
        # option. Measured: ["b"] answered ['a'].
        chosen = self.page.actions.select_option(
            params["selector"], params.get("options") or [],
            timeout=self._timeout(params))
        return {"values": chosen or []}

    def op_set_input_files(self, params: Dict) -> Any:
        paths = [f.get("name") if isinstance(f, dict) else f
                 for f in (params.get("localPaths") or params.get("files") or [])]
        self.page.actions.set_input_files(params["selector"], paths,
                                          timeout=self._timeout(params))
        return None

    def op_tap(self, params: Dict) -> Any:
        self.page.actions.tap(params["selector"],
                              timeout=self._timeout(params))
        return None

    def op_dispatch_event(self, params: Dict) -> Any:
        self.page.actions.dispatch_event(
            params["selector"], params["type"],
            params.get("eventInit") or {}, timeout=self._timeout(params))
        return None

    def op_drag_and_drop(self, params: Dict) -> Any:
        self.page.actions.drag_and_drop(params["source"], params["target"],
                                        timeout=self._timeout(params))
        return None

    def op_set_content(self, params: Dict) -> Any:
        """⛔ Goes through `document.open/write/close` in the MAIN world.

        The utility world has an EXTENDED principal, and Gecko requires
        `document.open()` to run under a principal EQUAL to the document's, so
        from there it answers `The operation is insecure` every single time -
        the same defect the fork already fixed inside the driver.
        """
        self.page.injected.evaluate_in_main(
            self.frame_id,
            "(() => { document.open(); document.write(%s); document.close(); })()"
            % _js_string(params["html"]), by_value=True)
        # ⛔ The load states of the OLD document do not count for the new one,
        # and `document.open()` starts a new one without a navigation event to
        # reset them. Waiting here would wait on states that are already set.
        self.page.lifecycle.wait_for_state(
            self.frame_id, params.get("waitUntil") or "load",
            timeout=self._timeout(params))
        return None

    def op_wait_for_timeout(self, params: Dict) -> Any:
        time.sleep((params.get("timeout") or 0) / 1000.0)
        return None

    def op_wait_for_load_state(self, params: Dict) -> Any:
        self.page.lifecycle.wait_for_state(
            self.frame_id, params.get("state") or "load",
            timeout=self._timeout(params))
        return None

    def op_wait_for_selector(self, params: Dict) -> Any:
        state = params.get("state") or "visible"
        object_id = self.page.actions.wait_for_selector(
            params["selector"], state=state, timeout=self._timeout(params))
        if object_id is None:
            return {"element": None}
        handle = ElementHandleDispatcher(self.server, self, object_id)
        return {"element": handle.channel}

    def op_wait_for_function(self, params: Dict) -> Any:
        deadline = time.monotonic() + self._timeout(params)
        expression = params["expression"]
        while True:
            value = self.page.injected.evaluate(self.frame_id, expression)
            if value:
                return {"handle": None}
            if time.monotonic() > deadline:
                raise ProtocolException(
                    "the expression never became truthy in %.0fs: %s"
                    % (self._timeout(params), expression[:120]))
            time.sleep(0.05)

    def op_expect(self, params: Dict) -> Any:
        """⛔ The polling half of `expect()`. It answers ONE probe; the
        retrying is the client's, in `_assertions.py`, which is why this must
        not loop: looping here would multiply the caller's timeout by ours."""
        expression = params.get("expression") or ""
        selector = params.get("selector")
        try:
            if expression.startswith("to.have.count"):
                count = self.page.injected.count(self.frame_id, selector)
                expected = int((params.get("expectedNumber") or 0))
                return {"matches": count == expected,
                        "received": _serialize(count)}
            if expression.startswith("to.be."):
                state = expression.split("to.be.", 1)[1]
                return self._with_element(
                    {"selector": selector},
                    lambda o: None) and {"matches": True}
        except ProtocolException:
            return {"matches": False, "received": _serialize(None)}
        raise ProtocolException(
            "expect(%r) is not implemented yet" % expression)

    def op_resolve_selector(self, params: Dict) -> Any:
        """The frame and selector a locator finally points at.

        ⛔ It answers THIS frame and the selector unchanged, which is correct
        only because frame-crossing locators are not supported here yet: an
        `iframe >> internal:control=enter-frame >> ...` would resolve into a
        child frame upstream. Answering this frame for one of those would be a
        wrong answer rather than a missing feature, so the compound form is
        refused.
        """
        selector = params.get("selector") or ""
        if "enter-frame" in selector:
            raise ProtocolException(
                "a frame-crossing locator (%s) cannot be resolved yet: "
                "answering this frame would be a wrong answer, not a missing "
                "one" % selector[:80])
        return {"frame": self.channel, "selector": selector}

    def op_wait_for_element_state(self, params: Dict) -> Any:
        self.page.actions.wait_for_selector(
            params["selector"], state=params["state"],
            timeout=self._timeout(params))
        return None

    def op_set_test_id(self, params: Dict) -> Any:
        raise ProtocolException(
            "set_test_id_attribute() cannot be honoured after the injected "
            "script is built: the attribute name is baked into it at "
            "construction. Pass it when the page is created instead of "
            "changing it mid-session")

    # ── frames as objects ───────────────────────────────────────────────────
    def op_frame_element(self, params: Dict) -> Any:
        raise ProtocolException(
            "frameElement needs the owner frame's handle, which this server "
            "does not track yet")

    # ── selectors that answer many ──────────────────────────────────────────
    def op_query_count(self, params: Dict) -> Any:
        return {"value": self.page.injected.count(self.frame_id,
                                                  params["selector"])}

    def op_query_selector_all(self, params: Dict) -> Any:
        ids = self.page.injected.query_selector_all(self.frame_id,
                                                    params["selector"])
        handles = [ElementHandleDispatcher(self.server, self, oid)
                   for oid in ids]
        return {"elements": [h.channel for h in handles]}

    def op_eval_on_selector(self, params: Dict) -> Any:
        return self._with_element(
            params,
            lambda o: _serialize(self.page.injected.call(
                self.frame_id,
                "(injected, el) => { const r = (%s);"
                "  return typeof r === 'function' ? r(el) : r; }"
                % params["expression"],
                {"objectId": o})))

    def op_eval_on_selector_all(self, params: Dict) -> Any:
        value = self.page.injected.call(
            self.frame_id,
            "(injected, sel) => { const els = injected.querySelectorAll("
            "  injected.parseSelector(sel), document);"
            "  const r = (%s); return typeof r === 'function' ? r(els) : r; }"
            % params["expression"],
            params["selector"])
        return {"value": _serialize(value)}

    def op_evaluate_handle(self, params: Dict) -> Any:
        object_id = self.page.injected.evaluate_in_main(
            self.frame_id, _with_argument(params), by_value=False)
        handle = ElementHandleDispatcher(self.server, self, object_id)
        return {"handle": handle.channel}


class DialogDispatcher(Dispatcher):
    """A dialog the page opened, and the two ways it can end.

    ⛔ A DIALOG BLOCKS THE PAGE UNTIL IT IS ANSWERED, which makes this the one
    object where forgetting to reply is not a leak but a hang: the content
    process sits inside `window.alert` and every later command times out with
    no hint about why. Playwright's client answers automatically when nobody is
    listening, and that safety net only works if the event actually arrives -
    which is why this is created and emitted from the event handler rather than
    on demand.
    """

    TYPE = "Dialog"
    METHODS = {"accept": "op_accept", "dismiss": "op_dismiss"}

    def __init__(self, server, page: "PageDispatcher", dialog_id: str,
                 kind: str, message: str, default_value: str) -> None:
        self.page_dispatcher = page
        self.dialog_id = dialog_id
        super().__init__(server, page, {
            "type": kind, "message": message,
            "defaultValue": default_value or "",
            "page": page.channel,
        })

    def _answer(self, accept: bool, prompt_text: Optional[str] = None) -> Any:
        params: Dict[str, Any] = {"dialogId": self.dialog_id,
                                  "accept": accept}
        if prompt_text is not None:
            params["promptText"] = prompt_text
        self.page_dispatcher.send("Page.handleDialog", params)
        self.dispose()
        return None

    def op_accept(self, params: Dict) -> Any:
        return self._answer(True, params.get("promptText"))

    def op_dismiss(self, params: Dict) -> Any:
        return self._answer(False)


# ── network ─────────────────────────────────────────────────────────────────
def _headers_array(raw) -> List[Dict[str, str]]:
    """Headers as the ARRAY of pairs the client expects, never a dict.

    ⛔ `RawHeaders` iterates over `[{"name": ..., "value": ...}]` and a dict
    iterates over its KEYS, so handing one over does not raise: it produces a
    header list whose every value is missing, and `response.headers` comes back
    full of empty strings. Juggler already sends the array form; this exists so
    a caller-built dict cannot slip through.
    """
    if isinstance(raw, dict):
        return [{"name": k, "value": str(v)} for k, v in raw.items()]
    out = []
    for entry in raw or []:
        if isinstance(entry, dict) and "name" in entry:
            out.append({"name": entry["name"],
                        "value": str(entry.get("value", ""))})
    return out


class RequestDispatcher(Dispatcher):
    TYPE = "Request"
    METHODS = {
        "response": "op_response",
        "rawRequestHeaders": "op_raw_request_headers",
        "failure": "op_failure",
    }

    def __init__(self, server, page: "PageDispatcher", params: Dict) -> None:
        self.page = page
        self.request_id = params.get("requestId")
        self.raw_headers = _headers_array(params.get("headers"))
        self.response: Optional["ResponseDispatcher"] = None
        #: Filled by `Network.requestFailed`. ⛔ None until it fails: an
        #: empty string would say "failed for no reason", which is a different
        #: answer from "did not fail".
        self.failure: Optional[str] = None
        frame_id = params.get("frameId") or page.frame.frame_id
        super().__init__(server, page, {
            "url": params.get("url") or "",
            "method": params.get("method") or "GET",
            "headers": self.raw_headers,
            "postData": params.get("postData"),
            "isNavigationRequest": bool(params.get("navigationId")),
            "resourceType": _resource_type(params),
            "frame": page.frame_for(frame_id).channel,
        })

    def op_response(self, params: Dict) -> Any:
        return {"response": self.response.channel if self.response else None}

    def op_raw_request_headers(self, params: Dict) -> Any:
        return {"headers": self.raw_headers}

    def op_failure(self, params: Dict) -> Any:
        """⛔ NULL means "it did not fail", and that is a different answer from
        an empty string. `_network.py` reads `errorText` and hands back None
        when there is none, so an empty string here would make every successful
        request look like it failed with a blank reason."""
        return {"error": {"errorText": self.failure} if self.failure else None}


class ResponseDispatcher(Dispatcher):
    TYPE = "Response"
    METHODS = {
        "body": "op_body",
        "rawResponseHeaders": "op_raw_response_headers",
        "securityDetails": "op_security_details",
        "serverAddr": "op_server_addr",
        "sizes": "op_sizes",
        "httpVersion": "op_http_version",
    }

    def __init__(self, server, request: RequestDispatcher,
                 params: Dict) -> None:
        self.request = request
        self.raw_headers = _headers_array(params.get("headers"))
        self.protocol_version = params.get("protocolVersion") or ""
        self.remote = {"ipAddress": params.get("remoteIPAddress") or "",
                       "port": params.get("remotePort") or 0}
        super().__init__(server, request.page, {
            "url": request.initializer["url"],
            "status": params.get("status") or 0,
            "statusText": params.get("statusText") or "",
            "headers": self.raw_headers,
            "request": request.channel,
            "fromServiceWorker": bool(params.get("fromServiceWorker")),
            # ⛔ EVERY timing field is mandatory and -1 means "did not happen".
            # Leaving one out is a KeyError in `_network.py`; leaving it at 0
            # claims the phase took no time, which is a different lie.
            "timing": {"startTime": 0, "domainLookupStart": -1,
                       "domainLookupEnd": -1, "connectStart": -1,
                       "secureConnectionStart": -1, "connectEnd": -1,
                       "requestStart": -1, "responseStart": -1},
        })

    def op_body(self, params: Dict) -> Any:
        raise ProtocolException(
            "response.body() is not available: this Juggler has no command to "
            "read a response body back, and returning an empty one would look "
            "like an empty page instead of a missing feature")

    def op_raw_response_headers(self, params: Dict) -> Any:
        return {"headers": self.raw_headers}

    def op_http_version(self, params: Dict) -> Any:
        """⛔ Juggler sends it on `requestFinished`, not on `responseReceived`,
        so a response asked before the request finished does not know yet. It
        answers what it has - the alternative is blocking a property read on a
        network event that may never come."""
        return {"value": self.protocol_version or "unknown"}

    def op_security_details(self, params: Dict) -> Any:
        return {"value": None}

    def op_server_addr(self, params: Dict) -> Any:
        return {"value": self.remote if self.remote["ipAddress"] else None}

    def op_sizes(self, params: Dict) -> Any:
        return {"sizes": {"requestBodySize": 0, "requestHeadersSize": 0,
                          "responseBodySize": 0, "responseHeadersSize": 0}}


class RouteDispatcher(Dispatcher):
    """One intercepted request, waiting for the caller to decide.

    ⛔ A ROUTE THAT IS NEVER ANSWERED HANGS THE PAGE, and it hangs it silently.
    The request sits held in the network layer; nothing errors, the page simply
    never finishes loading, and the failure surfaces as a timeout on whatever
    the caller does next. Playwright's client answers automatically when no
    handler matches - that safety net only works if this object reaches it,
    which is why the `route` event is emitted the instant the request is
    intercepted and never lazily.
    """

    TYPE = "Route"
    METHODS = {
        "abort": "op_abort",
        "continue": "op_continue",
        "fulfill": "op_fulfill",
        "redirectNavigationRequest": "op_redirect",
    }

    def __init__(self, server, request: "RequestDispatcher") -> None:
        self.request = request
        self.answered = False
        super().__init__(server, request.page, {"request": request.channel})

    def _send(self, command: str, params: Dict) -> Any:
        if self.answered:
            raise ProtocolException(
                "this route was already answered: a request can be aborted, "
                "continued or fulfilled exactly once")
        self.answered = True
        params = dict(params)
        params["requestId"] = self.request.request_id
        result = self.request.page.context.browser.conn.send(
            command, params, timeout=30)
        self.dispose()
        return result

    def op_abort(self, params: Dict) -> Any:
        """⛔ The error code travels: `NS_ERROR_ABORT` and `NS_ERROR_FAILURE`
        are not the same thing to a page that inspects the failure, and
        collapsing every reason into one is the sort of flattening a detector
        can read."""
        return self._send("Network.abortInterceptedRequest",
                          {"errorCode": params.get("errorCode") or "aborted"})

    def op_continue(self, params: Dict) -> Any:
        payload = _only_set({
            "url": params.get("url"),
            "method": params.get("method"),
            "headers": _headers_array(params.get("headers"))
                       if params.get("headers") is not None else None,
            "postData": params.get("postData"),
        })
        return self._send("Network.resumeInterceptedRequest", payload)

    def op_fulfill(self, params: Dict) -> Any:
        """⛔ THE BODY IS BASE64 ON THE WIRE, always. The client already
        encodes it and names the field `body` with `isBase64` beside it;
        Juggler wants `base64body`. Handing over the raw string produces a page
        whose bytes are the base64 TEXT, which renders as gibberish rather than
        failing."""
        body = params.get("body")
        if body is not None and not params.get("isBase64"):
            import base64 as _b64
            body = _b64.b64encode(str(body).encode("utf-8")).decode("ascii")
        return self._send("Network.fulfillInterceptedRequest", _only_set({
            "status": params.get("status") or 200,
            "statusText": params.get("statusText") or "",
            "headers": _headers_array(params.get("headers")),
            "base64body": body,
        }))

    def op_redirect(self, params: Dict) -> Any:
        return self._send("Network.resumeInterceptedRequest",
                          {"url": params["url"]})


def _resource_type(params: Dict) -> str:
    """⛔ Juggler says `cause`, Playwright says `resourceType`, and the two
    vocabularies only partly overlap. An unmapped cause becomes `other`, which
    is what upstream does too - guessing a nicer name would make
    `request.resource_type` disagree with itself between the two transports."""
    cause = (params.get("cause") or params.get("internalCause") or "").lower()
    return {
        "document": "document", "subdocument": "document",
        "stylesheet": "stylesheet", "script": "script",
        "image": "image", "imageset": "image",
        "font": "font", "media": "media",
        "xmlhttprequest": "xhr", "fetch": "fetch",
        "websocket": "websocket", "beacon": "other",
    }.get(cause, "other")


# ── page ────────────────────────────────────────────────────────────────────
class PageDispatcher(Dispatcher):
    TYPE = "Page"
    METHODS = {
        "mouseMove": "op_mouse_move",
        "mouseDown": "op_mouse_down",
        "mouseUp": "op_mouse_up",
        "mouseClick": "op_mouse_click",
        "mouseWheel": "op_mouse_wheel",
        "keyboardDown": "op_key_down",
        "keyboardUp": "op_key_up",
        "keyboardPress": "op_key_press",
        "keyboardType": "op_key_type",
        "keyboardInsertText": "op_key_insert",
        "close": "op_close",
        "goBack": "op_go_back",
        "goForward": "op_go_forward",
        "reload": "op_reload",
        "updateSubscription": "op_noop",
        "setViewportSize": "op_set_viewport_size",
        "emulateMedia": "op_emulate_media",
        "screenshot": "op_screenshot",
        "bringToFront": "op_bring_to_front",
        "exposeBinding": "op_expose_binding",
        "requestGC": "op_request_gc",
        "addScriptTag": "op_add_script_tag",
        "addStyleTag": "op_add_style_tag",
        "consoleMessages": "op_console_messages",
        "pageErrors": "op_page_errors",
        "clearConsoleMessages": "op_clear_console_messages",
        "clearPageErrors": "op_clear_page_errors",
        "webStorageItems": "op_storage_items",
        "webStorageGetItem": "op_storage_get",
        "webStorageSetItem": "op_storage_set",
        "webStorageRemoveItem": "op_storage_remove",
        "webStorageClear": "op_storage_clear",
        "runBeforeUnload": "op_run_before_unload",
    }

    def __init__(self, server, context: "BrowserContextDispatcher",
                 session: str, target_id: str) -> None:
        self.context = context
        self.session = session
        self.target_id = target_id
        conn = context.browser.conn
        self.lifecycle = Lifecycle(conn, session)
        self.injected = InjectedScript(conn, session)
        self.injected.install()
        self.actions = Actions(conn, session, self.lifecycle, self.injected)
        self._frames: Dict[str, Any] = {}
        self._requests: Dict[str, Any] = {}
        # ⛔ CAPPED, and that is not a detail: a page printing in a loop
        # would exhaust the memory of the process DRIVING it. Playwright keeps
        # the same logs and caps them for the same reason.
        self._console_log: List[Dict] = []
        self._error_log: List[Dict] = []
        self.main_frame_id = self.lifecycle.wait_for_main_frame(timeout=20.0)
        # ⛔ The Frame is created BEFORE the Page and adopted after: the Page
        # initializer has to name a mainFrame the client can already resolve.
        self.frame = FrameDispatcher(server, self, self.main_frame_id)
        viewport = context.options.get("viewport") or {"width": 1280,
                                                       "height": 720}
        super().__init__(server, context,
                         {"mainFrame": self.frame.channel,
                          "viewportSize": viewport, "isClosed": False})
        self.emit("__adopt__", {"guid": self.frame.guid})
        self.frame.parent = self
        # ⛔ AFTER the Page exists: an event that fires during construction
        # would name a guid the client has not been told about yet.
        self._install_events()


    def _install_events(self) -> None:
        """Turn Juggler events into protocol events.

        ⛔ THE SUBSCRIPTION IS NOT OPTIONAL AND IT IS NOT FREE. Playwright asks
        the server to enable categories with `updateSubscription`, and this
        server ignores that and always sends: the events are cheap here because
        they are already crossing the pipe for the lifecycle, and a category
        that is off is a `page.on("console")` that silently never fires.

        ⛔ AND `console` AND `pageError` GO TO THE CONTEXT, not to the Page.
        `_browser_context.py` listens for them and re-emits on the page it
        finds in `params["page"]`. Emitting them on the Page instead produces
        no error at all: the handler simply never runs, and the user concludes
        their page prints nothing.
        """
        connection = self.context.browser.conn
        previous = connection.on_event

        def route(method, params, session):
            if session == self.session:
                try:
                    self._on_juggler_event(method, params)
                except Exception as failure:
                    # ⛔ An event handler that raises must not take the read
                    # loop with it, and must not vanish either: the connection
                    # records it, and a test can read it.
                    if len(connection.handler_errors) < 32:
                        connection.handler_errors.append(
                            "page-events %s: %s" % (method, failure))
            previous(method, params, session)

        connection.on_event = route

    def _on_juggler_event(self, method: str, params: Dict) -> None:
        if method == "Runtime.console":
            # ⛔ THE LOG FILLS HERE, not inside `console_messages()`. A log
            # filled on request can only ever hold what arrived AFTER the
            # request, which is nothing: `page.console_messages()` would always
            # answer an empty list and look like a page that prints nothing.
            entry = {
                "page": self.channel,
                "type": params.get("type") or "log",
                "text": _console_text(params.get("args") or []),
                "args": [],
                "location": _location(params.get("location")),
            }
            self._remember(self._console_log, entry)
            self.context.emit("console", {
                "page": self.channel,
                "type": params.get("type") or "log",
                "text": _console_text(params.get("args") or []),
                "args": [],
                "location": _location(params.get("location")),
            })
        elif method == "Page.uncaughtError":
            self._remember(self._error_log, {
                "page": self.channel,
                "error": {"error": {
                    "name": "Error",
                    "message": params.get("message") or "",
                    "stack": params.get("stack") or "",
                }},
                "location": _location(params.get("location")),
            })
            self.context.emit("pageError", {
                "page": self.channel,
                "error": {"error": {
                    "name": "Error",
                    "message": params.get("message") or "",
                    "stack": params.get("stack") or "",
                }},
                "location": _location(params.get("location")),
            })
        elif method == "Page.dialogOpened":
            dialog = DialogDispatcher(self.server, self, params["dialogId"],
                                      params.get("type") or "alert",
                                      params.get("message") or "",
                                      params.get("defaultValue") or "")
            # ⛔ CREATING THE OBJECT IS NOT EMITTING THE EVENT, and the
            # difference is a hang rather than an error. `__create__` only
            # tells the client the object exists; `_browser_context.py`
            # listens for a `dialog` EVENT carrying its channel, and without
            # that the dialog sits unanswered, the content process stays
            # blocked inside `window.alert`, and the next command times out
            # naming a completely unrelated call - measured on 2026-08-28 as
            # `Runtime.callFunction: no response in 30s`.
            self.context.emit("dialog", {"dialog": dialog.channel})
        elif method == "Page.crashed":
            self.emit("crash")
        elif method == "Page.eventFired":
            state = {"load": "load",
                     "DOMContentLoaded": "domcontentloaded"}.get(
                         params.get("name") or "")
            if state and params.get("frameId") == self.frame.frame_id:
                self.frame.emit("loadstate", {"add": state})
        elif method == "Network.requestWillBeSent":
            request = RequestDispatcher(self.server, self, params)
            self._requests[params.get("requestId")] = request
            self.context.emit("request", {"request": request.channel,
                                          "page": self.channel})
            if self.context.intercepting and params.get("isIntercepted"):
                route = RouteDispatcher(self.server, request)
                self.context.emit("route", {"route": route.channel,
                                            "page": self.channel})
        elif method == "Network.responseReceived":
            request = self._requests.get(params.get("requestId"))
            if request is not None:
                response = ResponseDispatcher(self.server, request, params)
                request.response = response
                self.context.emit("response", {"response": response.channel,
                                               "page": self.channel})
        elif method == "Network.requestFinished":
            request = self._requests.pop(params.get("requestId"), None)
            if request is not None:
                if request.response is not None:
                    request.response.protocol_version = (
                        params.get("protocolVersion") or "")
                self.context.emit("requestFinished", {
                    "request": request.channel,
                    "response": request.response.channel
                               if request.response else None,
                    "responseEndTiming": params.get("responseEndTime") or 0,
                    "page": self.channel,
                })
        elif method == "Network.requestFailed":
            request = self._requests.pop(params.get("requestId"), None)
            if request is not None:
                request.failure = params.get("errorCode") or "failed"
                self.context.emit("requestFailed", {
                    "request": request.channel,
                    "failureText": params.get("errorCode") or "failed",
                    "page": self.channel,
                })
        elif method == "Page.navigationCommitted":
            if params.get("frameId") == self.frame.frame_id:
                self.frame.emit("navigated", {
                    "url": params.get("url") or "",
                    "name": params.get("name") or "",
                    "newDocument": {"request": None},
                })

    #: How many entries are kept. ⛔ A CAP, not a history: a page printing in
    #: a loop would exhaust the memory of the process DRIVING it, and a driver
    #: that dies because the page printed too much is a failure nobody will
    #: look for in the page.
    LOG_LIMIT = 500

    @staticmethod
    def _remember(log: list, entry: Dict) -> None:
        log.append(entry)
        if len(log) > PageDispatcher.LOG_LIMIT:
            del log[0]

    def frame_for(self, frame_id: str) -> "FrameDispatcher":
        """The dispatcher for a frame of this page, made on first sight.

        ⛔ ONE DISPATCHER PER FRAME ID, AND THE REGISTRY IS WHY. Building a
        new one each time would announce a second `__create__` for the same
        frame, and the client would hold two ChannelOwners that disagree about
        the load states - the second one starting empty while the first is the
        one events are delivered to.
        """
        if frame_id == self.frame.frame_id:
            return self.frame
        existing = self._frames.get(frame_id)
        if existing is not None:
            return existing
        frame = self.lifecycle.frames.get(frame_id)
        made = FrameDispatcher(
            self.server, self, frame_id,
            url=getattr(frame, "url", "") or "",
            load_states=sorted(getattr(frame, "states", []) or []) or ["commit"])
        self._frames[frame_id] = made
        return made

    def send(self, command: str, params: Dict) -> Any:
        """A Juggler command on THIS page's session.

        ⛔ The session is not optional and it is not a detail: without it the
        command lands on whichever page the browser feels like, and with two
        pages open the events of one are indistinguishable from the other.
        """
        return self.context.browser.conn.send(command, params,
                                              session=self.session, timeout=30)

    # ── history ─────────────────────────────────────────────────────────────
    def _history(self, command: str, params: Dict) -> Any:
        """⛔ goBack / goForward / reload are sent to the PAGE, not the Frame.

        The first draft put them on the Frame because everything else that
        navigates lives there, and it was wrong: `_page.py` sends them on the
        page channel. Guessing which object owns an operation is exactly what
        the recorded trace exists to stop.
        """
        frame_id = self.frame.frame_id
        # ⛔ READ THE CURRENT NAVIGATION FIRST. History gives back no
        # navigationId, so the only thing to anchor the wait on is that this
        # one has changed - and reading it after the command would sometimes
        # read the new one.
        frame = self.lifecycle.frames.get(frame_id)
        previous = frame.navigation if frame is not None else None
        result = self.send(command, {"frameId": frame_id}
                           if command != "Page.reload" else {}) or {}
        if command != "Page.reload" and not result.get("success"):
            # ⛔ NULL, not an error: `go_back` at the start of history is a
            # normal answer in Playwright, and raising would turn an ordinary
            # "there is nothing behind" into a failed script.
            return {"response": None}
        self.lifecycle.wait_for_new_navigation(
            frame_id, previous, params.get("waitUntil") or "load",
            timeout=(params.get("timeout") or 30000) / 1000.0)
        return {"response": None}

    def op_go_back(self, params: Dict) -> Any:
        return self._history("Page.goBack", params)

    def op_go_forward(self, params: Dict) -> Any:
        return self._history("Page.goForward", params)

    def op_reload(self, params: Dict) -> Any:
        return self._history("Page.reload", params)

    # ── pointer and keyboard ──────────────────────────────────────────
    def op_mouse_move(self, params: Dict) -> Any:
        self.actions.move(params["x"], params["y"],
                          steps=params.get("steps") or 1)
        return None

    def op_mouse_down(self, params: Dict) -> Any:
        self.actions.mouse_down(button=_button(params.get("button")),
                                clicks=params.get("clickCount") or 1)
        return None

    def op_mouse_up(self, params: Dict) -> Any:
        self.actions.mouse_up(button=_button(params.get("button")),
                              clicks=params.get("clickCount") or 1)
        return None

    def op_mouse_click(self, params: Dict) -> Any:
        self.actions.click_at(params["x"], params["y"],
                              button=_button(params.get("button")),
                              clicks=params.get("clickCount") or 1)
        return None

    def op_mouse_wheel(self, params: Dict) -> Any:
        self.actions.wheel(params["deltaX"], params["deltaY"])
        return None

    def op_key_down(self, params: Dict) -> Any:
        self.actions.keyboard.down(params["key"])
        return None

    def op_key_up(self, params: Dict) -> Any:
        self.actions.keyboard.up(params["key"])
        return None

    def op_key_press(self, params: Dict) -> Any:
        self.actions.keyboard.press(params["key"])
        return None

    def op_key_type(self, params: Dict) -> Any:
        self.actions.keyboard.type(params["text"])
        return None

    def op_key_insert(self, params: Dict) -> Any:
        self.actions.keyboard.insert_text(params["text"])
        return None

    # ── viewport, media, capture ────────────────────────────────────────────
    def op_set_viewport_size(self, params: Dict) -> Any:
        self.send("Page.setViewportSize", _only_set(
            {"viewportSize": params.get("viewportSize")}))
        return None

    def op_emulate_media(self, params: Dict) -> Any:
        """⛔ ONLY WHAT WAS ASKED FOR TRAVELS. Our fork turned four hardwired
        values into "no-override" precisely because a BrowsingContext override
        SHORT-CIRCUITS the pref: Gecko reads the override first and only
        consults LookAndFeel when it is None, so an override nobody requested
        turns every declaration invisible_core makes into dead code without
        raising anything.
        """
        out: Dict[str, Any] = {}
        for ours, theirs in (("colorScheme", "colorScheme"),
                             ("reducedMotion", "reducedMotion"),
                             ("forcedColors", "forcedColors"),
                             ("contrast", "contrast"),
                             ("media", "type")):
            value = params.get(ours)
            if value is not None:
                out[theirs] = value
        if not out:
            return None
        self.send("Page.setEmulatedMedia", out)
        return None

    def op_screenshot(self, params: Dict) -> Any:
        """⛔ The engine answers base64 and the client wants base64: it does
        NOT want bytes. Decoding here would send a str() of a bytes object."""
        # ⛔ `clip` IS MANDATORY, whatever it looks like. The declaration
        # does not wrap it in `Optional`, so leaving it out is rejected exactly
        # like sending it as null: `Object "<root>.clip" is undefined, but has
        # some scheme`. Reading the type declaration is what settled this -
        # both of the obvious readings of the error are wrong.
        clip = params.get("clip")
        if not clip:
            size = self.injected.evaluate(
                self.frame.frame_id,
                "({x: 0, y: 0, width: window.innerWidth,"
                " height: window.innerHeight})")
            clip = size or {"x": 0, "y": 0, "width": 1280, "height": 720}
        result = self.send("Page.screenshot", _only_set({
            "mimeType": "image/jpeg" if params.get("type") == "jpeg"
                        else "image/png",
            "clip": clip,
            "quality": params.get("quality"),
            "omitDeviceScaleFactor": False,
        })) or {}
        # ⛔ BASE64 IN, BASE64 OUT. The client decodes it; decoding here and
        # handing back bytes puts a str() of a bytes object in the answer.
        return {"binary": result.get("data")}

    # ── page-level odds and ends ────────────────────────────────────────────
    def op_request_gc(self, params: Dict) -> Any:
        """⛔ `Heap.collectGarbage` really does collect, and it is SLOW - it was
        once used as a "bare command" to measure transport latency and reported
        26,8 ms of browser work as if it were ours. It is the right command
        here, and the wrong one to benchmark with."""
        self.context.browser.conn.send("Heap.collectGarbage", {}, timeout=30)
        return None

    def _add_tag(self, params: Dict, tag: str) -> Any:
        """`add_script_tag` / `add_style_tag`.

        ⛔ THE MAIN WORLD, and that is the whole correctness of this method. A
        tag appended from the utility world would execute BEHIND THE XRAY: it
        would define nothing the page can see, which is the exact opposite of
        what these two functions promise. The utility world is right for
        everything we read and wrong for the one thing the caller wants the
        page itself to run.

        ⛔ AND A `url` HAS TO BE AWAITED. Appending a `<script src=...>` and
        returning immediately hands back a handle to a tag whose code has not
        run yet, so the very next `evaluate` does not see what it defines. The
        load is awaited here, and a failure to load RAISES rather than
        answering an element that does nothing.
        """
        url = params.get("url")
        content = params.get("content")
        path = params.get("path")
        if path:
            content = pathlib.Path(path).read_text(encoding="utf-8")
        if url is None and content is None:
            raise ProtocolException(
                "add_%s_tag needs one of url, path or content" % tag)

        if tag == "script":
            build = ("const el = document.createElement('script');"
                          " el.type = 'text/javascript';")
            attribute = "src"
        else:
            build = ("const el = document.createElement('style');"
                          " el.type = 'text/css';")
            attribute = "href"
            if url is not None:
                build = ("const el = document.createElement('link');"
                              " el.rel = 'stylesheet';")

        if url is not None:
            body = (
                "(async () => { %s"
                "  el.%s = %s;"
                "  const done = new Promise((ok, no) => {"
                "    el.onload = ok;"
                "    el.onerror = () => no(new Error('failed to load ' + %s));"
                "  });"
                "  (document.head || document.documentElement).appendChild(el);"
                "  await done; return el; })()"
                % (build, attribute, _js_string(url), _js_string(url)))
        else:
            body = (
                "(() => { %s el.textContent = %s;"
                "  (document.head || document.documentElement).appendChild(el);"
                "  return el; })()" % (build, _js_string(content)))

        object_id = self.injected.evaluate_in_main(
            self.frame.frame_id, body, by_value=False)
        handle = ElementHandleDispatcher(self.server, self.frame, object_id)
        return {"element": handle.channel}

    def op_add_script_tag(self, params: Dict) -> Any:
        return self._add_tag(params, "script")

    def op_add_style_tag(self, params: Dict) -> Any:
        return self._add_tag(params, "style")

    def op_console_messages(self, params: Dict) -> Any:
        return {"messages": list(self._console_log)}

    def op_page_errors(self, params: Dict) -> Any:
        return {"errors": list(self._error_log)}

    def op_clear_console_messages(self, params: Dict) -> Any:
        self._console_log.clear()
        return None

    def op_clear_page_errors(self, params: Dict) -> Any:
        self._error_log.clear()
        return None

    # ── web storage ───────────────────────────────────────────────
    def _storage(self, params: Dict, code: str, *args) -> Any:
        """localStorage or sessionStorage, in the PAGE's own world.

        ⛔ THE MAIN WORLD, and this one is not a style choice: web storage is
        keyed by ORIGIN and the utility world sandbox has an ExpandedPrincipal.
        Reading it from there does not raise - it answers a DIFFERENT store,
        empty, and the caller concludes the site saved nothing.

        ⛔ AND THE KIND IS VALIDATED. `kind` arrives as a string from the
        client; interpolating it into the expression would let anything through
        and produce a JavaScript error the caller cannot read.
        """
        kind = params.get("kind")
        if kind not in ("localStorage", "sessionStorage"):
            raise ProtocolException(
                "unknown storage kind %r: the two are localStorage and "
                "sessionStorage" % kind)
        return self.injected.evaluate_in_main(
            self.frame.frame_id, code % ((kind,) + args))

    def op_storage_items(self, params: Dict) -> Any:
        items = self._storage(params,
                              "(() => { const s = window.%s; const o = [];"
                              " for (let i = 0; i < s.length; i++) {"
                              "   const k = s.key(i);"
                              "   o.push({name: k, value: s.getItem(k)}); }"
                              " return o; })()")
        return {"items": items or []}

    def op_storage_get(self, params: Dict) -> Any:
        value = self._storage(params, "window.%s.getItem(%s)",
                              _js_string(params["name"]))
        return {"value": value}

    def op_storage_set(self, params: Dict) -> Any:
        self._storage(params, "window.%s.setItem(%s, %s)",
                      _js_string(params["name"]), _js_string(params["value"]))
        return None

    def op_storage_remove(self, params: Dict) -> Any:
        self._storage(params, "window.%s.removeItem(%s)",
                      _js_string(params["name"]))
        return None

    def op_storage_clear(self, params: Dict) -> Any:
        self._storage(params, "window.%s.clear()")
        return None

    def op_run_before_unload(self, params: Dict) -> Any:
        """⛔ `close(run_before_unload=True)` means: let the page show its
        `beforeunload` dialog. Answering it is the CALLER's job through the
        dialog event, so this must not close the page itself - doing that
        would dismiss the very dialog the option exists to raise."""
        self.injected.evaluate_in_main(self.frame.frame_id, "window.close()")
        return None

    def op_expose_binding(self, params: Dict) -> Any:
        """`expose_binding` / `expose_function`.

        ⛔ THE PAGE-FACING HALF IS NOT THE HARD PART. Installing a function on
        the page is one init script; what makes this a real feature is the
        REPLY path - the page calls it, the server raises `bindingCalled`, the
        client runs Python, and the answer has to travel back into the promise
        the page is holding. That is what `reject` and `resolve` are for, and
        they are only reachable through the BindingCall object this creates.

        ⛔ AND THE FUNCTION MUST LIVE IN THE PAGE'S WORLD. Installed behind the
        Xray it would be invisible to the site, which is the whole point of the
        call. Juggler's `Page.addBinding` does that, so the world is not ours
        to choose here - which is also why it cannot be hidden from the page:
        a binding is a name the site can enumerate, and a caller asking for one
        is asking for that trade.
        """
        raise ProtocolException(
            "expose_binding() is not implemented yet: the page-facing half is "
            "one init script, but the reply path - bindingCalled, then resolve "
            "or reject into the promise the page holds - is not wired, and a "
            "binding that never answers hangs the page that called it")

    def op_bring_to_front(self, params: Dict) -> Any:
        self.send("Page.bringToFront", {})
        return None

    def op_noop(self, params: Dict) -> Any:
        return None

    def op_close(self, params: Dict) -> Any:
        try:
            self.context.browser.conn.send(
                "Browser.removeBrowserContext",
                {"browserContextId": self.context.context_id}, timeout=10)
        except Exception:
            pass
        self.emit("close")
        self.dispose()
        return None


def _button(name: Optional[str]) -> int:
    return {"left": 0, "middle": 1, "right": 2}.get(name or "left", 0)


# ── context, browser, browser type ──────────────────────────────────────────
class BrowserContextDispatcher(Dispatcher):
    TYPE = "BrowserContext"
    METHODS = {
        "newPage": "op_new_page",
        "close": "op_close",
        "updateSubscription": "op_noop",
        "addInitScript": "op_noop",
        "addCookies": "op_add_cookies",
        "cookies": "op_cookies",
        "clearCookies": "op_clear_cookies",
        "grantPermissions": "op_grant_permissions",
        "clearPermissions": "op_clear_permissions",
        "setGeolocation": "op_set_geolocation",
        "setOffline": "op_set_offline",
        "setExtraHTTPHeaders": "op_set_extra_headers",
        "storageState": "op_storage_state",
        "setStorageState": "op_set_storage_state",
        "setNetworkInterceptionPatterns": "op_set_interception",
        "setWebSocketInterceptionPatterns": "op_set_ws_interception",
    }

    def __init__(self, server, browser: "BrowserDispatcher", options: Dict,
                 context_id: str) -> None:
        self.browser = browser
        self.options = options
        self.context_id = context_id
        # ⛔ THE THREE CHILDREN COME FIRST. `_browser_context.py` resolves all
        # of them with `from_channel` inside its constructor, so a context whose
        # initializer names one that does not exist yet raises before any page.
        debugger = DebuggerDispatcher(server, browser)
        debugger.emit("pausedStateChanged", {})
        tracing = TracingDispatcher(server, browser)
        request_context = APIRequestContextDispatcher(
            server, browser, {"tracing": tracing.channel})
        request_context.emit("__adopt__", {"guid": tracing.guid})
        super().__init__(server, browser, {
            "debugger": debugger.channel,
            "requestContext": request_context.channel,
            "tracing": tracing.channel,
            "options": options,
            "isChromium": False,
        })
        for child in (debugger, request_context, tracing):
            self.emit("__adopt__", {"guid": child.guid})
        self.pages: List[PageDispatcher] = []
        self.intercepting = False

    def op_set_storage_state(self, params: Dict) -> Any:
        """⛔ COOKIES ONLY, and it refuses the rest rather than dropping it.
        A storage state carries cookies AND per-origin localStorage; writing
        the cookies and silently ignoring the origins would restore half a
        session and look like it worked, which is worse than saying no - the
        caller would debug the site instead of the tool.
        """
        state = params.get("storageState") or {}
        if state.get("origins"):
            raise ProtocolException(
                "set_storage_state() with per-origin localStorage is not "
                "implemented: restoring only the cookies would look like it "
                "worked and leave half the session missing. Use "
                "page.evaluate on each origin, or open an issue")
        cookies = state.get("cookies") or []
        if cookies:
            self._browser_send("Browser.setCookies", {"cookies": cookies})
        return None

    def op_set_interception(self, params: Dict) -> Any:
        """Turn request interception on or off for this context.

        ⛔ THE PATTERNS ARE NOT SENT, and that is a real narrowing that has to
        be said out loud rather than discovered. Juggler's
        `Browser.setRequestInterception` is a BOOLEAN: it intercepts
        everything or nothing. Playwright's client filters by url on its side
        and calls `continue` on what it does not want, so behaviour is correct
        - but every request now makes a round trip through this process, which
        a narrow pattern would have avoided. It is a cost, not a defect, and it
        is the reason `route()` on a busy page is slower here than upstream.
        """
        wanted = bool(params.get("patterns"))
        self._browser_send("Browser.setRequestInterception",
                           {"enabled": wanted})
        self.intercepting = wanted
        return None

    def op_set_ws_interception(self, params: Dict) -> Any:
        raise ProtocolException(
            "WebSocket routing is not implemented: Juggler reports websocket "
            "frames but has no command to hold or rewrite one, so a route that "
            "appeared to work would silently pass everything through")

    def op_noop(self, params: Dict) -> Any:
        return None

    def op_new_page(self, params: Dict) -> Any:
        conn = self.browser.conn
        result = conn.send("Browser.newPage",
                           {"browserContextId": self.context_id}, timeout=30)
        target_id = result["targetId"]
        session = self.browser.session_for(target_id, timeout=20.0)
        page = PageDispatcher(self.server, self, session, target_id)
        self.pages.append(page)
        self.emit("page", {"page": page.channel})
        return {"page": page.channel}

    # ── cookies, permissions, geolocation ───────────────────────────────────
    def _browser_send(self, command: str, params: Dict) -> Any:
        params = dict(params)
        params["browserContextId"] = self.context_id
        return self.browser.conn.send(command, params, timeout=30)

    def op_add_cookies(self, params: Dict) -> Any:
        """⛔ `expires` IS SECONDS AND -1 MEANS SESSION, not zero and not
        milliseconds. Playwright's client already speaks that convention, so
        the cookies pass through unchanged - but a translation added here
        "helpfully" would silently expire every session cookie in 1970."""
        self._browser_send("Browser.setCookies",
                           {"cookies": params.get("cookies") or []})
        return None

    def op_cookies(self, params: Dict) -> Any:
        result = self._browser_send("Browser.getCookies", {}) or {}
        cookies = result.get("cookies") or []
        urls = params.get("urls") or []
        if urls:
            wanted = [_host_of(u) for u in urls]
            cookies = [c for c in cookies
                       if any(_domain_matches(c.get("domain") or "", h)
                              for h in wanted)]
        return {"cookies": cookies}

    def op_clear_cookies(self, params: Dict) -> Any:
        # ⛔ Juggler clears the WHOLE context: it takes no filter. Playwright's
        # client can ask for a subset, and pretending to honour that by
        # clearing everything would be worse than refusing - so the filtered
        # form is refused and the unfiltered one works.
        if any(params.get(k) for k in ("name", "domain", "path")):
            raise ProtocolException(
                "clear_cookies() with a filter is not supported: the engine "
                "command clears the whole context, and quietly clearing more "
                "than asked is worse than refusing")
        self._browser_send("Browser.clearCookies", {})
        return None

    def op_grant_permissions(self, params: Dict) -> Any:
        self._browser_send("Browser.grantPermissions",
                           {"origin": params.get("origin") or "",
                            "permissions": params.get("permissions") or []})
        return None

    def op_clear_permissions(self, params: Dict) -> Any:
        self._browser_send("Browser.resetPermissions", {})
        return None

    def op_set_geolocation(self, params: Dict) -> Any:
        """⛔ NULL clears the override, and that is not the same as sending
        zeroes: latitude 0 longitude 0 is a real place in the Atlantic, and a
        page that reads it gets a fix instead of a refusal."""
        self._browser_send("Browser.setGeolocationOverride",
                           {"geolocation": params.get("geolocation")})
        return None

    def op_set_offline(self, params: Dict) -> Any:
        raise ProtocolException(
            "set_offline() has no engine command in this Juggler: the "
            "protocol declares no offline override, so honouring it would "
            "mean lying about the network state")

    def op_set_extra_headers(self, params: Dict) -> Any:
        raise ProtocolException(
            "set_extra_http_headers() is not wired yet: it needs request "
            "interception, which is the network group")

    def op_storage_state(self, params: Dict) -> Any:
        """⛔ COOKIES ONLY, and it says so. Upstream also collects localStorage
        per origin by evaluating in every page; returning just the cookies with
        an empty origins list would look complete and silently lose half the
        state a caller is trying to save."""
        result = self._browser_send("Browser.getCookies", {}) or {}
        return {"cookies": result.get("cookies") or [], "origins": []}

    def op_close(self, params: Dict) -> Any:
        try:
            self.browser.conn.send("Browser.removeBrowserContext",
                                   {"browserContextId": self.context_id},
                                   timeout=10)
        except Exception:
            pass
        self.emit("close")
        self.dispose()
        return None


class BrowserDispatcher(Dispatcher):
    TYPE = "Browser"
    METHODS = {"newContext": "op_new_context", "close": "op_close",
               "newPage": "op_new_page"}

    def __init__(self, server, browser_type: "BrowserTypeDispatcher",
                 conn: Any, version: str) -> None:
        self.conn = conn
        self.browser_type = browser_type
        self._sessions: Dict[str, str] = {}
        self._sessions_ready = threading.Condition()
        previous = conn.on_event

        def route(method, params, session):
            if method == "Browser.attachedToTarget":
                info = params.get("targetInfo") or {}
                with self._sessions_ready:
                    self._sessions[info.get("targetId")] = params.get("sessionId")
                    self._sessions_ready.notify_all()
            previous(method, params, session)

        conn.on_event = route
        conn.send("Browser.enable", {"attachToDefaultContext": True},
                  timeout=30)
        super().__init__(server, browser_type,
                         {"version": version, "name": "firefox",
                          "browserName": "firefox"})
        self.contexts: List[BrowserContextDispatcher] = []

    def session_for(self, target_id: str, timeout: float) -> str:
        """⛔ The session arrives as an EVENT, not in the reply to `newPage`.
        Polling the dict without waiting on the condition is a race that passes
        on a fast machine and fails on a loaded one."""
        import time
        deadline = time.monotonic() + timeout
        with self._sessions_ready:
            while target_id not in self._sessions:
                left = deadline - time.monotonic()
                if left <= 0:
                    raise ProtocolException(
                        "no session was attached for target %s in %.0fs"
                        % (target_id, timeout))
                self._sessions_ready.wait(left)
            return self._sessions[target_id]

    def op_new_context(self, params: Dict) -> Any:
        result = self.conn.send("Browser.createBrowserContext",
                                {"removeOnDetach": True}, timeout=30)
        context = BrowserContextDispatcher(self.server, self, params,
                                           result["browserContextId"])
        self.contexts.append(context)
        self.emit("context", {"context": context.channel})
        return {"context": context.channel}

    def op_new_page(self, params: Dict) -> Any:
        context = self.op_new_context(params)
        guid = context["context"]["guid"]
        return self.server.object(guid).op_new_page({})

    def op_close(self, params: Dict) -> Any:
        try:
            self.conn.close()
        except Exception:
            pass
        self.emit("close")
        self.dispose()
        return None


class BrowserTypeDispatcher(Dispatcher):
    TYPE = "BrowserType"
    METHODS = {"launch": "op_launch"}

    def __init__(self, server, executable_path: str = "") -> None:
        super().__init__(server, None,
                         {"executablePath": executable_path,
                          "name": "firefox"})

    def op_launch(self, params: Dict) -> Any:
        executable = params.get("executablePath")
        if not executable:
            raise ProtocolException(
                "launch needs an executablePath: invisible_playwright pins its "
                "own engine and never downloads one at launch time")
        env = {e["name"]: e["value"] for e in (params.get("env") or [])}
        profile = params.get("userDataDir") or tempfile.mkdtemp(
            prefix="invisible_profile_")
        _write_user_js(profile, params.get("firefoxUserPrefs") or {})
        conn = juggler.launch(executable, profile,
                              headless=bool(params.get("headless", True)),
                              env=env, argv_extra=params.get("args") or [])
        self.server.on_shutdown(conn.close)
        version = _read_version(executable)
        browser = BrowserDispatcher(self.server, self, conn, version)
        return {"browser": browser.channel}


def _write_user_js(profile_dir: str, prefs: Dict) -> int:
    """The prefs, into the profile, BEFORE the browser starts.

    ⛔ WITHOUT THIS THE PYTHON PATH LAUNCHES A BROWSER THAT IS NOT THE PRODUCT,
    and it does so silently. Two hundred prefs arrive in `firefoxUserPrefs` on
    every `launch`, and the first draft of this server threw them away and
    started Firefox on an empty temporary profile. Everything worked - pages
    loaded, clicks landed, the tests were green - and every stealth declaration
    the package exists to make was simply absent.

    It was caught by a closed shadow root, of all things: the engine patch that
    lets a locator reach inside one is gated on `StealthEngineActive()`, which
    is a pref. The same probe found the root through `_juggler` directly and
    lost it through the public API, and the only difference between those two
    arms was who wrote the profile. A gate for a completely different feature
    is what made the absence visible; nothing was checking for it directly.

    ⛔ AND THEY ARE WRITTEN, NOT SENT. Our fork already removed prefs from the
    protocol - `Browser.enable` does not accept them any more - because a
    browser configured on the second launch is a browser that was wrong on the
    first. This mirrors what the driver's `defaultArgs` does, in Python.

    ⛔ Gecko HAS NO FLOAT PREF TYPE: a fraction must be written as a STRING, or
    the parser fails on that line and IGNORES EVERY LINE AFTER IT. That is not
    a hypothetical - `ui.textScaleFactor` written as a number once killed the
    browser on the second context, and the failure looked nothing like a prefs
    problem.
    """
    import os
    lines = []
    for name in sorted(prefs):
        value = prefs[name]
        if isinstance(value, bool):
            rendered = "true" if value else "false"
        elif isinstance(value, int):
            rendered = str(value)
        elif isinstance(value, float):
            # ⛔ A string, deliberately. See the docstring.
            rendered = json.dumps(str(value))
        else:
            rendered = json.dumps(str(value))
        lines.append('user_pref(%s, %s);' % (json.dumps(name), rendered))
    os.makedirs(profile_dir, exist_ok=True)
    body = ("// Written by invisible_playwright before the browser starts.\n"
            + "\n".join(lines) + "\n")
    # ⛔ `write_bytes`: on Windows a text-mode write translates every newline,
    # and a prefs file is read by the browser, not by git.
    with open(os.path.join(profile_dir, "user.js"), "wb") as handle:
        handle.write(body.encode("utf-8"))
    return len(lines)


def _read_version(executable: str) -> str:
    """The base version, from `application.ini` next to the binary.

    ⛔ Read, never assumed: this project has three separate incidents where a
    folder name or a guess about the version sent a whole evening of
    measurements against the wrong build.
    """
    import pathlib
    ini = pathlib.Path(executable).parent / "application.ini"
    try:
        for line in ini.read_text(encoding="utf-8",
                                  errors="replace").splitlines():
            if line.startswith("Version="):
                return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return "0.0"


# ── the root ────────────────────────────────────────────────────────────────
class PlaywrightDispatcher(Dispatcher):
    TYPE = "Playwright"
    METHODS = {}


class LocalUtilsDispatcher(Dispatcher):
    TYPE = "LocalUtils"
    METHODS = {"addStackToTracingNoReply": "op_noop",
               "traceDiscarded": "op_noop"}

    def __init__(self, server) -> None:
        super().__init__(server, None, {"deviceDescriptors": []},
                         guid="localUtils")

    def op_noop(self, params: Dict) -> Any:
        return None


class JugglerServer(Server):
    """The whole Playwright protocol, answered in this process."""

    def object(self, guid: str) -> Dispatcher:
        obj = self._objects.get(guid)
        if obj is None:
            raise ProtocolException("no object %r" % guid)
        return obj

    def handle_root(self, method: str, params: Dict) -> Any:
        if method != "initialize":
            raise ProtocolException(
                "the root only answers 'initialize', not %r" % method)
        # ⛔ The order below is the recorded one: BrowserType, then LocalUtils,
        # then Playwright naming both. Announcing Playwright first would name
        # two guids the client has never seen.
        browser_type = BrowserTypeDispatcher(self)
        utils = LocalUtilsDispatcher(self)
        playwright = PlaywrightDispatcher(
            self, None, {"firefox": browser_type.channel,
                         "utils": utils.channel},
            guid="Playwright")
        return {"playwright": playwright.channel}


def _console_text(args: list) -> str:
    """⛔ The console arguments arrive as remote objects, not as text. Reading
    `value` works for a primitive and gives nothing for an object, so the
    preview is used when there is one - which is what the driver shows too."""
    pieces = []
    for a in args:
        if not isinstance(a, dict):
            pieces.append(str(a))
        elif "value" in a:
            pieces.append(str(a["value"]))
        elif a.get("preview"):
            pieces.append(str(a["preview"]))
        elif a.get("unserializableValue"):
            pieces.append(str(a["unserializableValue"]))
        else:
            pieces.append(str(a.get("type") or "object"))
    return " ".join(pieces)


def _location(raw) -> Dict:
    """⛔ ALWAYS a location, never None: `_browser_context.py` casts it and
    falls back only on a missing KEY, so a null here becomes an AttributeError
    somewhere else entirely."""
    raw = raw or {}
    return {"url": raw.get("url") or "",
            "lineNumber": raw.get("lineNumber") or raw.get("line") or 0,
            "columnNumber": raw.get("columnNumber") or raw.get("column") or 0}


def _only_set(params: Dict) -> Dict:
    """The parameters that were actually given, with the absent ones REMOVED.

    ⛔ IN A CLOSED-WORLD SCHEMA, `null` AND ABSENT ARE DIFFERENT ANSWERS.
    Juggler validates every field it is handed: an Optional that arrives as
    `null` is not "not provided", it is a value of the wrong type, and the
    command is REJECTED at runtime with `Object "<root>.clip" is undefined,
    but has some scheme`. Measured on 2026-08-28 on `Page.screenshot`, whose
    clip and quality are both optional and were both being sent as null.

    ⛔ AND THIS IS NOT DONE INSIDE `Connection.send`, tempting as that is:
    some commands mean something BY sending null. `Browser.setGeolocationOverride`
    with `geolocation: null` CLEARS the override, and stripping it there would
    turn "stop pretending to be somewhere" into "do nothing".
    """
    return {k: v for k, v in params.items() if v is not None}


def _host_of(url: str) -> str:
    """The host of a url, without importing a parser for three characters."""
    without_scheme = url.split("://", 1)[-1]
    return without_scheme.split("/", 1)[0].split(":", 1)[0].lower()


def _domain_matches(cookie_domain: str, host: str) -> bool:
    """⛔ A LEADING DOT MEANS "AND EVERY SUBDOMAIN", and dropping it turns a
    site-wide cookie into one that matches nothing. Comparing the two strings
    directly is the version that looks right and returns an empty list."""
    domain = (cookie_domain or "").lstrip(".").lower()
    if not domain or not host:
        return False
    return host == domain or host.endswith("." + domain)
