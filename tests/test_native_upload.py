import asyncio
import ctypes
from pathlib import Path
import sys
import threading
from types import SimpleNamespace

import pytest

from invisible_playwright import native_upload
from invisible_playwright.native_upload import _normalise_files


def test_cancelled_chooser_waiter_cannot_leak_lock(monkeypatch):
    chooser_lock = threading.Lock()
    monkeypatch.setattr(native_upload, "_CHOOSER_LOCK", chooser_lock)

    async def exercise() -> None:
        chooser_lock.acquire()
        waiter = asyncio.create_task(
            native_upload._acquire_chooser_lock(timeout_seconds=1.0)
        )
        await asyncio.sleep(0.02)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter

        chooser_lock.release()
        await asyncio.wait_for(
            native_upload._acquire_chooser_lock(timeout_seconds=0.2),
            timeout=0.5,
        )
        chooser_lock.release()

    asyncio.run(exercise())


def test_normalise_files_resolves_and_validates(tmp_path):
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"media")

    assert _normalise_files([media]) == [str(media.resolve())]


def test_normalise_files_rejects_empty_and_missing(tmp_path):
    with pytest.raises(ValueError, match="At least one file"):
        _normalise_files([])
    with pytest.raises(FileNotFoundError):
        _normalise_files([Path(tmp_path) / "missing.mp4"])


def test_native_upload_allows_pending_click_after_windows_accepts(monkeypatch):
    class Locator:
        async def get_attribute(self, _name):
            return None

        async def evaluate(self, _expression, timeout):
            return 1

    class Trigger:
        async def click(self, **_kwargs):
            await asyncio.Event().wait()

    def find_dialog(
        _before,
        found,
        _stop,
        result,
        _timeout_seconds,
        _owner_process_ids,
        _owner_session_token,
    ):
        result["hwnd"] = 123
        found.set()

    monkeypatch.setattr(native_upload, "_snapshot_dialogs", lambda: set())
    monkeypatch.setattr(native_upload, "_watch_new_dialog", find_dialog)
    monkeypatch.setattr(native_upload, "_fill_and_accept", lambda _hwnd, _files: None)
    monkeypatch.setattr(native_upload, "_cancel_dialog", lambda _hwnd: None)
    monkeypatch.setattr(native_upload, "_CLICK_COMPLETION_TIMEOUT_SECONDS", 0.01)

    asyncio.run(
        native_upload.set_input_files_native(
            Locator(),
            [__file__],
            trigger=Trigger(),
            allow_input_replacement=True,
            timeout_ms=1_000,
        )
    )


def test_fill_and_accept_uses_direct_win32_controls(monkeypatch):
    state = {"text": "", "clicked": False}

    def enum_children(_hwnd, callback, extra):
        callback(201, extra)

    def send_message(hwnd, message, _wparam, value):
        if hwnd == 202 and message == 245:
            state["clicked"] = True

    class FakeUser32:
        def SetFocus(self, _hwnd):
            return 201

        def SendMessageW(self, _hwnd, message, _wparam, value):
            if message == 194:
                state["text"] = ctypes.wstring_at(value)
            return 1

    fake_gui = SimpleNamespace(
        EnumChildWindows=enum_children,
        GetClassName=lambda hwnd: "Edit" if hwnd == 201 else "Button",
        IsWindowVisible=lambda _hwnd: True,
        IsWindowEnabled=lambda _hwnd: True,
        SendMessage=send_message,
        GetWindowText=lambda _hwnd: state["text"],
        GetDlgItem=lambda _hwnd, control_id: 202 if control_id == 1 else 0,
    )
    fake_con = SimpleNamespace(EM_SETSEL=177, EM_REPLACESEL=194, BM_CLICK=245)
    monkeypatch.setitem(sys.modules, "win32gui", fake_gui)
    monkeypatch.setitem(sys.modules, "win32con", fake_con)
    monkeypatch.setattr(
        native_upload.ctypes,
        "windll",
        SimpleNamespace(user32=FakeUser32()),
    )

    native_upload._fill_and_accept(100, [r"C:\media\clip.mp4"])

    assert state == {"text": r"C:\media\clip.mp4", "clicked": True}


def test_fill_and_accept_allows_unreadable_cross_process_edit(monkeypatch):
    state = {"clicked": False, "wrapper_value": ""}

    class FakeUser32:
        def SetFocus(self, _hwnd):
            return 201

        def SendMessageW(self, _hwnd, _message, _wparam, _value):
            return 1

    class FakeEditWrapper:
        def __init__(self, _hwnd):
            pass

        def set_edit_text(self, value):
            state["wrapper_value"] = value

    fake_gui = SimpleNamespace(
        EnumChildWindows=lambda _hwnd, callback, extra: callback(201, extra),
        GetClassName=lambda _hwnd: "Edit",
        IsWindowVisible=lambda _hwnd: True,
        IsWindowEnabled=lambda _hwnd: True,
        GetWindowText=lambda _hwnd: "",
        GetDlgItem=lambda _hwnd, control_id: 202 if control_id == 1 else 0,
        SendMessage=lambda hwnd, message, _wparam, _value: state.update(
            clicked=bool(hwnd == 202 and message == 245)
        ),
    )
    fake_con = SimpleNamespace(EM_SETSEL=177, EM_REPLACESEL=194, BM_CLICK=245)
    monkeypatch.setitem(sys.modules, "win32gui", fake_gui)
    monkeypatch.setitem(sys.modules, "win32con", fake_con)
    monkeypatch.setitem(
        sys.modules,
        "pywinauto.controls.win32_controls",
        SimpleNamespace(EditWrapper=FakeEditWrapper),
    )
    monkeypatch.setattr(
        native_upload.ctypes,
        "windll",
        SimpleNamespace(user32=FakeUser32()),
    )

    native_upload._fill_and_accept(100, [r"C:\media\clip.mp4"])

    assert state == {
        "clicked": True,
        "wrapper_value": r"C:\media\clip.mp4",
    }


def test_fill_and_accept_types_with_wm_char_when_text_setters_are_ignored(monkeypatch):
    state = {"clicked": False, "text": ""}

    class FakeUser32:
        def SetFocus(self, _hwnd):
            return 201

        def SendMessageW(self, _hwnd, message, wparam, _value):
            if message == 0x0303:  # WM_CLEAR
                state["text"] = ""
            elif message == 0x0102:  # WM_CHAR
                state["text"] += chr(wparam)
            return 1

    class IgnoredEditWrapper:
        def __init__(self, _hwnd):
            pass

        def set_edit_text(self, _value):
            return None

    fake_gui = SimpleNamespace(
        EnumChildWindows=lambda _hwnd, callback, extra: callback(201, extra),
        GetClassName=lambda _hwnd: "Edit",
        IsWindowVisible=lambda _hwnd: True,
        IsWindowEnabled=lambda _hwnd: True,
        GetWindowText=lambda _hwnd: state["text"],
        GetDlgItem=lambda _hwnd, control_id: 202 if control_id == 1 else 0,
        SendMessage=lambda hwnd, message, _wparam, _value: state.update(
            clicked=bool(hwnd == 202 and message == 245)
        ),
    )
    fake_con = SimpleNamespace(EM_SETSEL=177, EM_REPLACESEL=194, BM_CLICK=245)
    monkeypatch.setitem(sys.modules, "win32gui", fake_gui)
    monkeypatch.setitem(sys.modules, "win32con", fake_con)
    monkeypatch.setitem(
        sys.modules,
        "pywinauto.controls.win32_controls",
        SimpleNamespace(EditWrapper=IgnoredEditWrapper),
    )
    monkeypatch.setattr(
        native_upload.ctypes,
        "windll",
        SimpleNamespace(user32=FakeUser32()),
    )

    diagnostics = native_upload._fill_and_accept(
        100, [r"C:\media\clip.mp4"]
    )

    assert state == {"clicked": True, "text": r"C:\media\clip.mp4"}
    assert diagnostics["wm_char_text_matches"] is True


def test_firefox_dialog_must_belong_to_requested_session(monkeypatch):
    fake_process = SimpleNamespace(exe=lambda: r"C:\browser\firefox.exe")
    monkeypatch.setitem(
        sys.modules,
        "psutil",
        SimpleNamespace(Process=lambda _pid: fake_process),
    )
    monkeypatch.setitem(
        sys.modules,
        "win32process",
        SimpleNamespace(GetWindowThreadProcessId=lambda _hwnd: (10, 321)),
    )

    assert native_upload._is_firefox_dialog(100, frozenset({321})) is True
    assert native_upload._is_firefox_dialog(100, frozenset({999})) is False
