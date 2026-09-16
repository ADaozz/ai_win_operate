from __future__ import annotations

import ctypes
import os
from ctypes import wintypes

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.windows.emergency_stop import EmergencyStopHotkey
import app.windows.emergency_stop as emergency_stop_module


class FakeHotkeyBackend:
    def __init__(self, registered: bool = True) -> None:
        self.registered = registered
        self.calls: list[tuple[object, ...]] = []

    def register(self, hotkey_id: int, virtual_key: int) -> bool:
        self.calls.append(("register", hotkey_id, virtual_key))
        return self.registered

    def unregister(self, hotkey_id: int) -> None:
        self.calls.append(("unregister", hotkey_id))


def test_global_f8_message_invokes_emergency_callback() -> None:
    app = QApplication.instance() or QApplication([])
    backend = FakeHotkeyBackend()
    callbacks: list[str] = []
    hotkey = EmergencyStopHotkey(lambda: callbacks.append("stop"), "F8", backend)
    hotkey.install(app)

    message = wintypes.MSG()
    message.message = emergency_stop_module._WM_HOTKEY
    message.wParam = emergency_stop_module._HOTKEY_ID
    handled, result = hotkey.nativeEventFilter(b"windows_generic_MSG", ctypes.addressof(message))

    assert handled is True
    assert result == 0
    assert callbacks == ["stop"]
    assert backend.calls[0][0] == "register"

    hotkey.close(app)
    assert backend.calls[-1][0] == "unregister"
    app.processEvents()


@pytest.mark.parametrize("key", ["F0", "F13", "ESC", ""])
def test_emergency_stop_rejects_non_function_key(key: str) -> None:
    with pytest.raises(ValueError, match="F1 through F12"):
        EmergencyStopHotkey(lambda: None, key, FakeHotkeyBackend())
