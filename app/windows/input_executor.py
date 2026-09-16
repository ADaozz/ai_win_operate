"""SendInput-based mouse and keyboard execution for one target HWND."""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from typing import Literal, Protocol

from app.common.exceptions import (
    InputExecutionError,
    UnsupportedPlatformError,
)
from app.windows.models import WindowInfo

MouseButton = Literal["left", "right"]
ScrollDirection = Literal["up", "down"]

_INPUT_MOUSE = 0
_INPUT_KEYBOARD = 1
_KEYEVENTF_KEYUP = 0x0002
_KEYEVENTF_UNICODE = 0x0004
_MOUSEEVENTF_LEFTDOWN = 0x0002
_MOUSEEVENTF_LEFTUP = 0x0004
_MOUSEEVENTF_RIGHTDOWN = 0x0008
_MOUSEEVENTF_RIGHTUP = 0x0010
_MOUSEEVENTF_WHEEL = 0x0800
_WHEEL_DELTA = 120

_VK_CODES = {
    "BACKSPACE": 0x08,
    "TAB": 0x09,
    "ENTER": 0x0D,
    "RETURN": 0x0D,
    "SHIFT": 0x10,
    "CTRL": 0x11,
    "ALT": 0x12,
    "ESC": 0x1B,
    "SPACE": 0x20,
    "PAGEUP": 0x21,
    "PAGEDOWN": 0x22,
    "END": 0x23,
    "HOME": 0x24,
    "LEFT": 0x25,
    "UP": 0x26,
    "RIGHT": 0x27,
    "DOWN": 0x28,
    "DELETE": 0x2E,
}
_VK_CODES.update({chr(code): code for code in range(ord("A"), ord("Z") + 1)})
_VK_CODES.update({str(number): 0x30 + number for number in range(10)})
_VK_CODES.update({f"F{number}": 0x6F + number for number in range(1, 13)})


class _MouseInput(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class _KeyboardInput(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class _HardwareInput(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _InputUnion(ctypes.Union):
    _fields_ = [
        ("mi", _MouseInput),
        ("ki", _KeyboardInput),
        ("hi", _HardwareInput),
    ]


class _Input(ctypes.Structure):
    _anonymous_ = ("data",)
    _fields_ = [("type", wintypes.DWORD), ("data", _InputUnion)]


class InputWindowManager(Protocol):
    def get_window(self, hwnd: int) -> WindowInfo: ...

    def is_minimized(self, hwnd: int) -> bool: ...

    def focus(self, hwnd: int) -> None: ...


class InputBackend(Protocol):
    def get_foreground_window(self) -> int: ...

    def set_cursor_position(self, x: int, y: int) -> None: ...

    def click(self, button: MouseButton, clicks: int) -> None: ...

    def type_text(self, text: str) -> None: ...

    def hotkey(self, keys: list[str]) -> None: ...

    def scroll(self, delta: int) -> None: ...


class SendInputBackend:
    """Thin, pointer-size-safe wrapper around the Windows SendInput API."""

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise UnsupportedPlatformError("Input execution is available only on Windows")

        self._user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        self._user32.SendInput.argtypes = [
            wintypes.UINT,
            ctypes.POINTER(_Input),
            ctypes.c_int,
        ]
        self._user32.SendInput.restype = wintypes.UINT
        self._user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
        self._user32.SetCursorPos.restype = wintypes.BOOL
        self._user32.GetForegroundWindow.restype = wintypes.HWND

    def get_foreground_window(self) -> int:
        handle = self._user32.GetForegroundWindow()
        return int(handle) if handle else 0

    def set_cursor_position(self, x: int, y: int) -> None:
        if not self._user32.SetCursorPos(x, y):
            raise InputExecutionError(f"Unable to move cursor to ({x}, {y})")

    def click(self, button: MouseButton, clicks: int) -> None:
        flags = {
            "left": (_MOUSEEVENTF_LEFTDOWN, _MOUSEEVENTF_LEFTUP),
            "right": (_MOUSEEVENTF_RIGHTDOWN, _MOUSEEVENTF_RIGHTUP),
        }
        down, up = flags[button]
        inputs: list[_Input] = []
        for _ in range(clicks):
            inputs.extend((self._mouse_input(down), self._mouse_input(up)))
        self._send(inputs)

    def type_text(self, text: str) -> None:
        inputs: list[_Input] = []
        index = 0
        while index < len(text):
            character = text[index]
            if character in ("\r", "\n"):
                if character == "\r" and index + 1 < len(text) and text[index + 1] == "\n":
                    index += 1
                inputs.append(self._keyboard_input(_VK_CODES["ENTER"], 0, 0))
                inputs.append(
                    self._keyboard_input(_VK_CODES["ENTER"], 0, _KEYEVENTF_KEYUP)
                )
            else:
                encoded = character.encode("utf-16-le")
                for offset in range(0, len(encoded), 2):
                    code_unit = int.from_bytes(encoded[offset : offset + 2], "little")
                    inputs.append(
                        self._keyboard_input(0, code_unit, _KEYEVENTF_UNICODE)
                    )
                    inputs.append(
                        self._keyboard_input(
                            0,
                            code_unit,
                            _KEYEVENTF_UNICODE | _KEYEVENTF_KEYUP,
                        )
                    )
            index += 1
        self._send(inputs)

    def hotkey(self, keys: list[str]) -> None:
        virtual_keys = [self._virtual_key(key) for key in keys]
        inputs = [self._keyboard_input(key, 0, 0) for key in virtual_keys]
        inputs.extend(
            self._keyboard_input(key, 0, _KEYEVENTF_KEYUP)
            for key in reversed(virtual_keys)
        )
        self._send(inputs)

    def scroll(self, delta: int) -> None:
        mouse_data = ctypes.c_uint32(delta).value
        self._send([self._mouse_input(_MOUSEEVENTF_WHEEL, mouse_data)])

    def _send(self, inputs: list[_Input]) -> None:
        if not inputs:
            return
        input_array = (_Input * len(inputs))(*inputs)
        sent = self._user32.SendInput(
            len(inputs),
            input_array,
            ctypes.sizeof(_Input),
        )
        if sent != len(inputs):
            error_code = ctypes.get_last_error()
            raise InputExecutionError(
                f"SendInput accepted {sent}/{len(inputs)} events "
                f"(Windows error {error_code})"
            )

    @staticmethod
    def _mouse_input(flags: int, mouse_data: int = 0) -> _Input:
        return _Input(
            type=_INPUT_MOUSE,
            mi=_MouseInput(mouseData=mouse_data, dwFlags=flags),
        )

    @staticmethod
    def _keyboard_input(virtual_key: int, scan_code: int, flags: int) -> _Input:
        return _Input(
            type=_INPUT_KEYBOARD,
            ki=_KeyboardInput(
                wVk=virtual_key,
                wScan=scan_code,
                dwFlags=flags,
            ),
        )

    @staticmethod
    def _virtual_key(key: str) -> int:
        normalized = key.strip().upper()
        try:
            return _VK_CODES[normalized]
        except KeyError as exc:
            raise InputExecutionError(f"Unsupported key: {key}") from exc


class WindowsInputExecutor:
    """Execute input only after focusing and verifying the target HWND."""

    def __init__(
        self,
        window_manager: InputWindowManager,
        backend: InputBackend | None = None,
    ) -> None:
        self._window_manager = window_manager
        self._backend = backend or SendInputBackend()

    def click(
        self,
        hwnd: int,
        x: float,
        y: float,
        *,
        button: MouseButton = "left",
        clicks: int = 1,
    ) -> None:
        if button not in ("left", "right"):
            raise InputExecutionError(f"Unsupported mouse button: {button}")
        if clicks not in (1, 2):
            raise InputExecutionError("Click count must be 1 or 2")
        self._validate_normalized_coordinates(x, y)
        window = self._activate(hwnd)
        screen_x, screen_y = self._to_screen_coordinates(window, x, y)
        try:
            self._backend.set_cursor_position(screen_x, screen_y)
            self._assert_foreground(hwnd)
            self._backend.click(button, clicks)
        except InputExecutionError:
            raise
        except Exception as exc:
            raise InputExecutionError("Mouse click execution failed") from exc

    def double_click(self, hwnd: int, x: float, y: float) -> None:
        self.click(hwnd, x, y, clicks=2)

    def right_click(self, hwnd: int, x: float, y: float) -> None:
        self.click(hwnd, x, y, button="right")

    def type_text(self, hwnd: int, text: str) -> None:
        self._activate(hwnd)
        try:
            self._assert_foreground(hwnd)
            self._backend.type_text(text)
        except InputExecutionError:
            raise
        except Exception as exc:
            raise InputExecutionError("Text input execution failed") from exc

    def hotkey(self, hwnd: int, keys: list[str]) -> None:
        if not keys:
            raise InputExecutionError("Hotkey requires at least one key")
        self._activate(hwnd)
        try:
            self._assert_foreground(hwnd)
            self._backend.hotkey([key.strip().upper() for key in keys])
        except InputExecutionError:
            raise
        except Exception as exc:
            raise InputExecutionError("Hotkey execution failed") from exc

    def scroll(self, hwnd: int, direction: ScrollDirection, amount: int = 3) -> None:
        if direction not in ("up", "down"):
            raise InputExecutionError(f"Unsupported scroll direction: {direction}")
        if amount <= 0:
            raise InputExecutionError("Scroll amount must be positive")
        window = self._activate(hwnd)
        center_x, center_y = self._to_screen_coordinates(window, 0.5, 0.5)
        delta = _WHEEL_DELTA * amount * (1 if direction == "up" else -1)
        try:
            self._backend.set_cursor_position(center_x, center_y)
            self._assert_foreground(hwnd)
            self._backend.scroll(delta)
        except InputExecutionError:
            raise
        except Exception as exc:
            raise InputExecutionError("Scroll execution failed") from exc

    def _activate(self, hwnd: int) -> WindowInfo:
        window = self._window_manager.get_window(hwnd)
        if self._window_manager.is_minimized(hwnd):
            raise InputExecutionError(f"Target window is minimized: HWND {hwnd}")
        self._window_manager.focus(hwnd)
        if self._backend.get_foreground_window() != hwnd:
            raise InputExecutionError(
                f"Target window did not receive foreground focus: HWND {hwnd}"
            )
        return self._window_manager.get_window(hwnd)

    def _assert_foreground(self, hwnd: int) -> None:
        if self._backend.get_foreground_window() != hwnd:
            raise InputExecutionError(
                f"Target window lost foreground focus: HWND {hwnd}"
            )

    @staticmethod
    def _to_screen_coordinates(
        window: WindowInfo,
        x: float,
        y: float,
    ) -> tuple[int, int]:
        WindowsInputExecutor._validate_normalized_coordinates(x, y)
        offset_x = min(window.width - 1, round(window.width * x))
        offset_y = min(window.height - 1, round(window.height * y))
        return window.left + offset_x, window.top + offset_y

    @staticmethod
    def _validate_normalized_coordinates(x: float, y: float) -> None:
        if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
            raise InputExecutionError("Normalized coordinates must be between 0 and 1")
