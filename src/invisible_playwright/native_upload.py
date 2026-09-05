"""Trusted Windows file uploads for the patched engine's B178 path regression.

firefox-21 delivers Playwright's file-chooser event, but the repository's B178
tests still document that ``Page.setFileInputFiles`` rejects real paths. This
module keeps the browser on its normal headed-cloaked renderer and completes the
real Windows chooser without exposing it on the desktop.

The operating system, not page JavaScript, changes the input.  Consequently the
page receives browser-generated ``input`` and ``change`` events with
``isTrusted == true``, and large videos are never copied into a 50 MB-limited
protocol payload.
"""

from __future__ import annotations

import asyncio
import ctypes
import os
import threading
import time
from pathlib import Path
from typing import Any, Iterable, Sequence


_CHOOSER_LOCK = threading.Lock()
_DIALOG_CLASS = "#32770"
_DWMWA_CLOAK = 13
_FILE_NAME_CONTROL_ID = 1148
_CLICK_COMPLETION_TIMEOUT_SECONDS = 5.0
_CHOOSER_LOCK_WAIT_TIMEOUT_SECONDS = 90.0


async def _acquire_chooser_lock(
    timeout_seconds: float = _CHOOSER_LOCK_WAIT_TIMEOUT_SECONDS,
) -> None:
    """Acquire the process-wide chooser lock without leaking it on cancel.

    ``asyncio.to_thread(lock.acquire)`` cannot cancel the underlying blocking
    worker.  If its coroutine is cancelled while waiting, that orphaned worker
    can acquire the lock later and never release it, permanently blocking every
    following upload.  Polling a non-blocking acquire keeps ownership in the
    coroutine which will also run the matching ``finally`` block.
    """

    deadline = time.monotonic() + max(0.1, float(timeout_seconds))
    while True:
        if _CHOOSER_LOCK.acquire(blocking=False):
            return
        if time.monotonic() >= deadline:
            raise NativeUploadError(
                "Windows file chooser remained busy for "
                f"{float(timeout_seconds):g}s."
            )
        await asyncio.sleep(0.05)


class NativeUploadError(RuntimeError):
    """The trusted native chooser could not attach the requested files."""


def _normalise_files(paths: Iterable[os.PathLike[str] | str]) -> list[str]:
    files = [str(Path(value).expanduser().resolve()) for value in paths]
    if not files:
        raise ValueError("At least one file is required.")
    missing = [value for value in files if not Path(value).is_file()]
    if missing:
        raise FileNotFoundError(missing[0])
    return files


def _snapshot_dialogs() -> set[int]:
    import win32gui

    dialogs: set[int] = set()

    def collect(hwnd: int, _extra: Any) -> bool:
        try:
            if win32gui.GetClassName(hwnd) == _DIALOG_CLASS:
                dialogs.add(hwnd)
        except Exception:
            pass
        return True

    win32gui.EnumWindows(collect, None)
    return dialogs


def _is_firefox_dialog(
    hwnd: int,
    owner_process_ids: frozenset[int] | None = None,
    owner_session_token: Any | None = None,
) -> bool:
    import psutil
    import win32process

    try:
        _thread_id, process_id = win32process.GetWindowThreadProcessId(hwnd)
        process = psutil.Process(process_id)
        if owner_session_token is not None:
            if not owner_session_token.matches(process):
                return False
        elif owner_process_ids is not None and process_id not in owner_process_ids:
            return False
        return Path(process.exe()).name.casefold() == "firefox.exe"
    except Exception:
        return False


def _cloak_and_park(hwnd: int) -> None:
    import win32con
    import win32gui

    value = ctypes.c_int(1)
    cloak_result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
        ctypes.c_void_p(hwnd),
        _DWMWA_CLOAK,
        ctypes.byref(value),
        ctypes.sizeof(value),
    )
    # Windows may deny DWM attributes across integrity levels. Parking remains
    # reliable in that case and is also a second guard for RDP/compositors that
    # do not honour DWMWA_CLOAK.
    parked = False
    try:
        win32gui.SetWindowPos(
            hwnd,
            None,
            -6400,
            -6400,
            0,
            0,
            win32con.SWP_NOSIZE
            | win32con.SWP_NOACTIVATE
            | win32con.SWP_NOZORDER,
        )
        # pywin32 returns None on success; absence of an exception is the
        # success signal.
        parked = True
    except Exception:
        pass
    if not parked and cloak_result != 0:
        raise OSError(
            "Could not cloak or park the Windows chooser "
            f"(DWM HRESULT={cloak_result})."
        )


def _activate_hidden_dialog_offscreen(hwnd: int) -> None:
    """Give a pre-show common dialog an operable UI thread without flashing."""
    import win32con
    import win32gui

    # Position it before setting WS_VISIBLE so even compositors that apply DWM
    # cloak one frame late never draw it on the user's desktop.
    win32gui.SetWindowPos(
        hwnd,
        None,
        -6400,
        -6400,
        0,
        0,
        win32con.SWP_NOSIZE
        | win32con.SWP_NOACTIVATE
        | win32con.SWP_NOZORDER,
    )
    win32gui.ShowWindow(hwnd, win32con.SW_SHOWNOACTIVATE)
    _cloak_and_park(hwnd)
    time.sleep(0.15)


def _watch_new_dialog(
    before: set[int],
    found: threading.Event,
    stop: threading.Event,
    result: dict[str, Any],
    timeout_seconds: float,
    owner_process_ids: frozenset[int] | None = None,
    owner_session_token: Any | None = None,
) -> None:
    import psutil
    import win32gui
    import win32process

    deadline = time.monotonic() + timeout_seconds
    observed: dict[int, dict[str, Any]] = {}
    while not stop.is_set() and time.monotonic() < deadline:
        for hwnd in _snapshot_dialogs() - before:
            try:
                visible = bool(win32gui.IsWindowVisible(hwnd))
                if hwnd not in observed:
                    _thread_id, process_id = win32process.GetWindowThreadProcessId(hwnd)
                    try:
                        process_name = Path(psutil.Process(process_id).exe()).name
                    except Exception:
                        process_name = "<unreadable>"
                    observed[hwnd] = {
                        "hwnd": int(hwnd),
                        "pid": int(process_id),
                        "process": process_name,
                        "visible": visible,
                        "title": win32gui.GetWindowText(hwnd)[:120],
                    }
                    result["observed"] = list(observed.values())
                # A chooser created by a DWM-cloaked Firefox session can have
                # WS_VISIBLE cleared from its first frame. It is still a real,
                # fully operable #32770 dialog. Process ownership and creation
                # after the click are the authoritative identity checks.
                if not _is_firefox_dialog(
                    hwnd, owner_process_ids, owner_session_token
                ):
                    continue
                # A pre-show chooser must be shown once offscreen before its
                # filename control accepts focus/edit notifications. A chooser
                # Windows already marked visible can be cloaked immediately.
                if visible:
                    _cloak_and_park(hwnd)
                else:
                    _activate_hidden_dialog_offscreen(hwnd)
                result["hwnd"] = hwnd
                found.set()
                return
            except Exception as exc:
                result["error"] = exc
        time.sleep(0.003)
    found.set()


def _fill_and_accept(hwnd: int, files: Sequence[str]) -> dict[str, Any]:
    import win32con
    import win32gui

    # Keep this path independent from pywinauto. Its backend registry uses
    # dynamic imports and can behave differently after one-file compilation.
    # The common file chooser exposes ordinary Win32 Edit/Button children, so
    # direct messages are sufficient and survive packaging unchanged.
    edits: list[int] = []

    def collect_edit(child: int, _extra: Any) -> bool:
        try:
            if (
                win32gui.GetClassName(child) == "Edit"
                and win32gui.IsWindowEnabled(child)
            ):
                edits.append(int(child))
        except Exception:
            pass
        return True

    win32gui.EnumChildWindows(hwnd, collect_edit, None)
    if not edits:
        raise NativeUploadError("Windows file chooser has no File name control.")

    value = files[0] if len(files) == 1 else " ".join(f'"{path}"' for path in files)
    def control_id(edit: int) -> int:
        try:
            return int(win32gui.GetDlgCtrlID(edit))
        except Exception:
            return -1

    # Explorer-style Open dialogs can expose both the top-right Search box
    # and the File name edit as visible Edit controls. Enumeration order is
    # timing-dependent and changes in a one-file/CREATE_NO_WINDOW launch. The
    # language-independent Win32 control id is the stable selector.
    filename = next(
        (edit for edit in edits if control_id(edit) == _FILE_NAME_CONTROL_ID),
        next(
            (edit for edit in edits if win32gui.IsWindowVisible(edit)),
            edits[0],
        ),
    )
    diagnostics: dict[str, Any] = {
        "dialog_visible": bool(win32gui.IsWindowVisible(hwnd)),
        "edit_control_ids": [control_id(edit) for edit in edits],
        "selected_control_id": control_id(filename),
    }
    try:
        # The dialog lives on Firefox's UI thread. A pre-show chooser does not
        # accept Edit selection messages until Windows has assigned keyboard
        # focus once. It is already parked offscreen and DWM-cloaked here.
        win32gui.SetForegroundWindow(hwnd)
        win32gui.SetFocus(filename)
    except Exception:
        pass
    # Common dialogs ignore WM_SETTEXT on this ComboBox edit while it is
    # cloaked/parked. Mirror the reliable Edit control sequence: select all,
    # then replace the selection with a Unicode buffer.
    buffer = ctypes.create_unicode_buffer(value, size=len(value) + 1)
    user32 = ctypes.windll.user32
    try:
        from ctypes import wintypes

        user32.SendMessageW.argtypes = [
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]
        user32.SendMessageW.restype = ctypes.c_ssize_t
    except (AttributeError, TypeError):
        # Unit doubles need not implement ctypes function metadata.
        pass
    user32.SetFocus(ctypes.c_void_p(filename))
    user32.SendMessageW(
        ctypes.c_void_p(filename),
        win32con.EM_SETSEL,
        0,
        -1,
    )
    user32.SendMessageW(
        ctypes.c_void_p(filename),
        win32con.EM_REPLACESEL,
        1,
        ctypes.addressof(buffer),
    )
    actual_text = win32gui.GetWindowText(filename)
    diagnostics["win32_text_matches"] = actual_text == value
    if actual_text != value:
        try:
            # pywinauto's EditWrapper performs the additional focus/selection
            # notifications required by Explorer-style common dialogs. Import
            # the concrete module (not the dynamically resolved Desktop
            # backend) so one-file compilers can follow it deterministically.
            from pywinauto.controls.win32_controls import EditWrapper

            EditWrapper(filename).set_edit_text(value)
            diagnostics["pywinauto_fallback"] = "completed"
        except Exception as exc:
            diagnostics["pywinauto_fallback"] = (
                f"{type(exc).__name__}: {exc}"
            )
            # WM_GETTEXT can return an empty string for another process's
            # common-dialog Edit control even after the edit accepted the
            # value. Browser-side ``element.files`` below is the authoritative
            # verification; do not turn an unreadable OS control into a false
            # upload failure.
            pass

    # ``EditWrapper.set_edit_text`` can report completion even though the
    # Explorer-style dialog has not updated its internal File name model. Read
    # it back, then fall back to WM_CHAR messages. WM_CHAR contains no pointer
    # into this process, works across the Firefox process boundary, and emits
    # the same edit notifications as typed input without using the clipboard.
    fallback_text = win32gui.GetWindowText(filename)
    diagnostics["fallback_text_matches"] = fallback_text == value
    if fallback_text != value:
        user32.SetFocus(ctypes.c_void_p(filename))
        user32.SendMessageW(
            ctypes.c_void_p(filename),
            win32con.EM_SETSEL,
            0,
            -1,
        )
        user32.SendMessageW(ctypes.c_void_p(filename), 0x0303, 0, 0)  # WM_CLEAR
        for character in value:
            user32.SendMessageW(
                ctypes.c_void_p(filename),
                0x0102,  # WM_CHAR
                ord(character),
                0,
            )
        fallback_text = win32gui.GetWindowText(filename)
        diagnostics["wm_char_text_matches"] = fallback_text == value

    # Tell the common-dialog parent that control 1148 changed. Merely setting
    # the Edit text is insufficient on some Windows 10/11 dialog builds: the
    # visible text changes, but IDOK still reads an older empty value.
    control = control_id(filename) & 0xFFFF
    for notification in (0x0400, 0x0300):  # EN_UPDATE, EN_CHANGE
        user32.SendMessageW(
            ctypes.c_void_p(hwnd),
            0x0111,  # WM_COMMAND
            control | (notification << 16),
            filename,
        )

    time.sleep(0.35)

    # IDOK is language-independent, unlike the localized Open/Mở caption.
    open_button = win32gui.GetDlgItem(hwnd, 1)
    if not open_button:
        raise NativeUploadError("Windows file chooser has no Open button.")
    win32gui.SendMessage(open_button, win32con.BM_CLICK, 0, 0)
    diagnostics["open_clicked"] = True
    is_window = getattr(win32gui, "IsWindow", None)
    if callable(is_window):
        close_deadline = time.monotonic() + 3.0
        while is_window(hwnd) and time.monotonic() < close_deadline:
            time.sleep(0.05)
        diagnostics["dialog_closed_after_open"] = not bool(is_window(hwnd))
    return diagnostics


def _cancel_dialog(hwnd: int | None) -> None:
    if not hwnd:
        return
    try:
        import win32con
        import win32gui

        cancel = win32gui.GetDlgItem(hwnd, 2)
        if cancel:
            win32gui.SendMessage(cancel, win32con.BM_CLICK, 0, 0)
    except Exception:
        pass


async def set_input_files_native(
    locator: Any,
    paths: Iterable[os.PathLike[str] | str],
    *,
    trigger: Any | None = None,
    allow_input_replacement: bool = False,
    owner_process_ids: Iterable[int] | None = None,
    owner_session_token: Any | None = None,
    timeout_ms: int = 15_000,
) -> None:
    """Attach files through a real, DWM-cloaked Windows chooser.

    ``locator`` is a Playwright Locator for one ``<input type=file>``.  Pass the
    visible label/button that normally opens it as ``trigger`` when the input is
    hidden. Set ``allow_input_replacement`` for reactive pages which remove the
    input immediately after accepting a file; the caller must then verify the
    page's editor/progress state. The function briefly focuses an offscreen,
    DWM-cloaked dialog and never uses the clipboard. A process-wide lock serialises only the sub-second native
    selection stage so concurrent browser sessions cannot consume one another's
    chooser.
    """

    if os.name != "nt":
        raise NativeUploadError("Native trusted upload is currently Windows-only.")
    files = _normalise_files(paths)
    owner_ids = (
        frozenset(int(process_id) for process_id in owner_process_ids)
        if owner_process_ids is not None
        else None
    )
    if owner_ids is not None and not owner_ids:
        raise NativeUploadError("The Firefox session has no owned processes.")
    timeout_seconds = max(1.0, timeout_ms / 1000.0)
    await _acquire_chooser_lock()
    dialog_hwnd: int | None = None
    fill_diagnostics: dict[str, Any] | None = None
    click_task: asyncio.Task[Any] | None = None
    watcher: threading.Thread | None = None
    stop = threading.Event()
    try:
        multiple = await locator.get_attribute("multiple")
        if len(files) > 1 and multiple is None:
            raise NativeUploadError("The target file input does not allow multiple files.")

        before = await asyncio.to_thread(_snapshot_dialogs)
        found = threading.Event()
        watcher_result: dict[str, Any] = {}
        watcher = threading.Thread(
            target=_watch_new_dialog,
            args=(
                before,
                found,
                stop,
                watcher_result,
                timeout_seconds,
                owner_ids,
                owner_session_token,
            ),
            name="invpw-native-file-chooser",
            daemon=True,
        )
        watcher.start()
        click_target = trigger if trigger is not None else locator
        click_task = asyncio.create_task(
            click_target.click(no_wait_after=True, timeout=timeout_ms)
        )

        ready = await asyncio.wait_for(
            asyncio.to_thread(found.wait, timeout_seconds),
            timeout=timeout_seconds + 1,
        )
        if not ready or "hwnd" not in watcher_result:
            error = watcher_result.get("error")
            details: list[str] = []
            if error:
                details.append(f"watcher error={type(error).__name__}: {error}")
            observed = watcher_result.get("observed")
            if observed:
                details.append(f"observed dialogs={observed}")
            if click_task.done():
                try:
                    click_task.result()
                except Exception as click_error:
                    details.append(
                        "click error="
                        f"{type(click_error).__name__}: {click_error}"
                    )
                else:
                    details.append("click completed without opening a dialog")
            else:
                details.append("click command remained pending")
            detail = f" ({'; '.join(details)})" if details else ""
            raise NativeUploadError(f"Windows file chooser did not appear{detail}")
        dialog_hwnd = int(watcher_result["hwnd"])
        fill_diagnostics = await asyncio.to_thread(
            _fill_and_accept, dialog_hwnd, files
        )
        try:
            # Firefox can keep Playwright's click command pending even after
            # the native chooser has accepted the file and closed. The OS
            # chooser is the trusted source of the selection; for reactive
            # inputs the caller explicitly verifies the fresh editor/progress
            # state. Do not turn that harmless protocol lag into a false
            # native-upload failure.
            await asyncio.wait_for(
                asyncio.shield(click_task),
                timeout=_CLICK_COMPLETION_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError as exc:
            if not allow_input_replacement:
                raise NativeUploadError(
                    "Windows chooser accepted the file but the browser click "
                    "command did not settle."
                ) from exc

        expected = len(files)
        actual = 0
        # The native dialog closes before Firefox finishes updating the DOM
        # file list. Wait for that browser-side handoff instead of sampling the
        # input in the same event-loop tick as the Open button.
        dom_deadline = time.monotonic() + 5.0
        while time.monotonic() < dom_deadline:
            try:
                actual = await locator.evaluate(
                    "element => element.files.length",
                    timeout=1_000,
                )
            except Exception:
                if allow_input_replacement:
                    return
                raise
            if int(actual) == expected:
                break
            await asyncio.sleep(0.05)
        if int(actual) != expected:
            raise NativeUploadError(
                "File chooser closed but the input contains "
                f"{actual}/{expected} file(s). Diagnostics: {fill_diagnostics}"
            )
    finally:
        stop.set()
        if click_task is not None:
            if not click_task.done():
                click_task.cancel()
            await asyncio.gather(click_task, return_exceptions=True)
        if watcher is not None:
            await asyncio.to_thread(watcher.join, 1.0)
        _cancel_dialog(dialog_hwnd)
        _CHOOSER_LOCK.release()
