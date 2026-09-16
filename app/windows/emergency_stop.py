"""Windows global F-key hotkey for emergency Agent Runtime stop."""

from __future__ import annotations

import ctypes
import sys
from collections.abc import Callable
from ctypes import wintypes
from typing import Protocol

from PySide6.QtCore import QAbstractNativeEventFilter, QCoreApplication

from app.common.exceptions import (
    EmergencyStopRegistrationError,
    UnsupportedPlatformError,
)

_WM_HOTKEY = 0x0312
_MOD_NOREPEAT = 0x4000
_HOTKEY_ID = 0xA17E


class HotkeyBackend(Protocol):
    def register(self, hotkey_id: int, virtual_key: int) -> bool: ...

    def unregister(self, hotkey_id: int) -> None: ...


class Win32HotkeyBackend:
    def __init__(self) -> None:
        if sys.platform != "win32":
            raise UnsupportedPlatformError("Global emergency stop requires Windows")
        self._user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        self._user32.RegisterHotKey.argtypes = [
            wintypes.HWND,
            ctypes.c_int,
            wintypes.UINT,
            wintypes.UINT,
        ]
        self._user32.RegisterHotKey.restype = wintypes.BOOL
        self._user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        self._user32.UnregisterHotKey.restype = wintypes.BOOL

    def register(self, hotkey_id: int, virtual_key: int) -> bool:
        return bool(
            self._user32.RegisterHotKey(
                None,
                hotkey_id,
                _MOD_NOREPEAT,
                virtual_key,
            )
        )

    def unregister(self, hotkey_id: int) -> None:
        self._user32.UnregisterHotKey(None, hotkey_id)


class EmergencyStopHotkey(QAbstractNativeEventFilter):
    """Register a system-wide F-key and invoke a thread-safe stop callback."""

    def __init__(
        self,
        callback: Callable[[], None],
        key: str = "F8",
        backend: HotkeyBackend | None = None,
    ) -> None:
        super().__init__()
        self._callback = callback
        self._backend = backend or Win32HotkeyBackend()
        self._virtual_key = self._parse_function_key(key)
        self._installed = False

    def install(self, application: QCoreApplication) -> None:
        if self._installed:
            return
        if not self._backend.register(_HOTKEY_ID, self._virtual_key):
            raise EmergencyStopRegistrationError(
                "无法注册全局紧急停止键；该按键可能已被其他程序占用"
            )
        application.installNativeEventFilter(self)
        self._installed = True

    def close(self, application: QCoreApplication) -> None:
        if not self._installed:
            return
        application.removeNativeEventFilter(self)
        self._backend.unregister(_HOTKEY_ID)
        self._installed = False

    def nativeEventFilter(  # noqa: N802
        self,
        event_type: bytes,
        message: int,
    ) -> tuple[bool, int]:
        del event_type
        try:
            native_message = wintypes.MSG.from_address(int(message))
        except (TypeError, ValueError):
            return False, 0
        if (
            native_message.message == _WM_HOTKEY
            and int(native_message.wParam) == _HOTKEY_ID
        ):
            self._callback()
            return True, 0
        return False, 0

    @staticmethod
    def _parse_function_key(key: str) -> int:
        normalized = key.strip().upper()
        if not normalized.startswith("F") or not normalized[1:].isdigit():
            raise ValueError("Emergency stop key must be F1 through F12")
        number = int(normalized[1:])
        if not 1 <= number <= 12:
            raise ValueError("Emergency stop key must be F1 through F12")
        return 0x6F + number
