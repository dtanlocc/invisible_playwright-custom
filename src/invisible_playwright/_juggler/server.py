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

import tempfile
import threading
from typing import Any, Dict, List, Optional

from . import connection as juggler
from .actions import Actions
from .dispatcher import Dispatcher, ProtocolException, Server
from .injected import InjectedScript
from .lifecycle import Lifecycle


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
        return {"value": _serialize(self.page.injected.call(
            self.frame.frame_id,
            "(injected, el, expr) => (%s)(el)" % params["expression"],
            {"objectId": self.object_id}, params.get("expression")))}

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


def _serialize(value: Any) -> Any:
    """A Python value in the shape `parse_result` expects.

    ⛔ Playwright does not send bare JSON: it sends a tagged union, and
    `_connection.parse_value` reads the TAG. A bare `True` where `{"b": true}`
    is expected does not raise - it falls through to the object branch and comes
    back as something else entirely.
    """
    if value is None:
        return {"v": "null"}
    if isinstance(value, bool):
        return {"b": value}
    if isinstance(value, (int, float)):
        return {"n": value}
    if isinstance(value, str):
        return {"s": value}
    if isinstance(value, (list, tuple)):
        return {"a": [_serialize(x) for x in value]}
    if isinstance(value, dict):
        return {"o": [{"k": k, "v": _serialize(v)} for k, v in value.items()]}
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
        return {"value": _serialize(self.page.injected.evaluate(
            self.frame_id, params["expression"]))}

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
        "setDefaultNavigationTimeoutNoReply": "op_noop",
        "setDefaultTimeoutNoReply": "op_noop",
        "updateSubscription": "op_noop",
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

    # ── pointer and keyboard ────────────────────────────────────────────────
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
        "setDefaultNavigationTimeoutNoReply": "op_noop",
        "setDefaultTimeoutNoReply": "op_noop",
        "updateSubscription": "op_noop",
        "addInitScript": "op_noop",
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
        conn = juggler.launch(executable, profile,
                              headless=bool(params.get("headless", True)),
                              env=env, argv_extra=params.get("args") or [])
        self.server.on_shutdown(conn.close)
        version = _read_version(executable)
        browser = BrowserDispatcher(self.server, self, conn, version)
        return {"browser": browser.channel}


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
