from __future__ import annotations

import ctypes

import pytest

from app.common.exceptions import InputExecutionError
from app.windows.input_executor import (
    SendInputBackend,
    WindowsInputExecutor,
    _Input,
    _KeyboardInput,
    _MouseInput,
)
from app.windows.models import WindowInfo


def make_window(
    *,
    left: int = -100,
    top: int = 50,
    width: int = 1000,
    height: int = 600,
) -> WindowInfo:
    return WindowInfo(
        hwnd=77,
        title="Target",
        pid=88,
        left=left,
        top=top,
        width=width,
        height=height,
    )


class FakeManager:
    def __init__(self, window: WindowInfo, *, minimized: bool = False) -> None:
        self.window = window
        self.minimized = minimized
        self.focused: list[int] = []

    def get_window(self, hwnd: int) -> WindowInfo:
        assert hwnd == self.window.hwnd
        return self.window

    def is_minimized(self, hwnd: int) -> bool:
        assert hwnd == self.window.hwnd
        return self.minimized

    def focus(self, hwnd: int) -> None:
        self.focused.append(hwnd)


class FakeInputBackend:
    def __init__(self, foreground: int = 77) -> None:
        self.foreground = foreground
        self.positions: list[tuple[int, int]] = []
        self.clicks: list[tuple[str, int]] = []
        self.typed: list[str] = []
        self.hotkeys: list[list[str]] = []
        self.scrolls: list[int] = []

    def get_foreground_window(self) -> int:
        return self.foreground

    def set_cursor_position(self, x: int, y: int) -> None:
        self.positions.append((x, y))

    def click(self, button: str, clicks: int) -> None:
        self.clicks.append((button, clicks))

    def type_text(self, text: str) -> None:
        self.typed.append(text)

    def hotkey(self, keys: list[str]) -> None:
        self.hotkeys.append(keys)

    def scroll(self, delta: int) -> None:
        self.scrolls.append(delta)


def test_click_converts_normalized_coordinates_inside_window() -> None:
    manager = FakeManager(make_window())
    backend = FakeInputBackend()
    executor = WindowsInputExecutor(manager, backend)

    executor.click(77, 0.0, 1.0)
    executor.double_click(77, 1.0, 0.0)
    executor.right_click(77, 0.5, 0.5)

    assert backend.positions == [(-100, 649), (899, 50), (400, 350)]
    assert backend.clicks == [("left", 1), ("left", 2), ("right", 1)]
    assert manager.focused == [77, 77, 77]


def test_invalid_coordinates_are_rejected_before_focus_or_input() -> None:
    manager = FakeManager(make_window())
    backend = FakeInputBackend()
    executor = WindowsInputExecutor(manager, backend)

    with pytest.raises(InputExecutionError, match="between 0 and 1"):
        executor.click(77, 1.01, 0.5)

    assert manager.focused == []
    assert backend.positions == []


def test_executor_refuses_minimized_or_non_foreground_window() -> None:
    minimized_manager = FakeManager(make_window(), minimized=True)
    minimized_backend = FakeInputBackend()
    executor = WindowsInputExecutor(minimized_manager, minimized_backend)

    with pytest.raises(InputExecutionError, match="minimized"):
        executor.type_text(77, "blocked")
    assert minimized_manager.focused == []
    assert minimized_backend.typed == []

    manager = FakeManager(make_window())
    wrong_foreground = FakeInputBackend(foreground=999)
    executor = WindowsInputExecutor(manager, wrong_foreground)
    with pytest.raises(InputExecutionError, match="foreground"):
        executor.hotkey(77, ["CTRL", "A"])
    assert wrong_foreground.hotkeys == []


def test_executor_rechecks_foreground_immediately_before_input() -> None:
    class FocusLosingBackend(FakeInputBackend):
        def __init__(self) -> None:
            super().__init__()
            self.checks = 0

        def get_foreground_window(self) -> int:
            self.checks += 1
            return 77 if self.checks == 1 else 999

    backend = FocusLosingBackend()
    executor = WindowsInputExecutor(FakeManager(make_window()), backend)

    with pytest.raises(InputExecutionError, match="lost foreground"):
        executor.click(77, 0.5, 0.5)

    assert backend.positions == [(400, 350)]
    assert backend.clicks == []


def test_keyboard_and_scroll_actions_are_forwarded() -> None:
    manager = FakeManager(make_window())
    backend = FakeInputBackend()
    executor = WindowsInputExecutor(manager, backend)

    executor.type_text(77, "Hello 世界")
    executor.hotkey(77, ["ctrl", "a"])
    executor.scroll(77, "up", 3)
    executor.scroll(77, "down", 2)

    assert backend.typed == ["Hello 世界"]
    assert backend.hotkeys == [["CTRL", "A"]]
    assert backend.positions == [(400, 350), (400, 350)]
    assert backend.scrolls == [360, -240]


def test_send_input_accepts_return_as_enter_alias() -> None:
    assert SendInputBackend._virtual_key("RETURN") == 0x0D
    assert SendInputBackend._virtual_key("enter") == 0x0D


def test_invalid_scroll_and_empty_hotkey_are_rejected() -> None:
    executor = WindowsInputExecutor(FakeManager(make_window()), FakeInputBackend())

    with pytest.raises(InputExecutionError, match="positive"):
        executor.scroll(77, "down", 0)
    with pytest.raises(InputExecutionError, match="at least one"):
        executor.hotkey(77, [])


def test_send_input_structures_are_pointer_size_safe() -> None:
    pointer_size = ctypes.sizeof(ctypes.c_void_p)
    expected = (32, 24, 40) if pointer_size == 8 else (24, 16, 28)

    assert ctypes.sizeof(_MouseInput) == expected[0]
    assert ctypes.sizeof(_KeyboardInput) == expected[1]
    assert ctypes.sizeof(_Input) == expected[2]
    assert dict(_MouseInput._fields_)["dwExtraInfo"] is ctypes.c_size_t
    assert dict(_KeyboardInput._fields_)["dwExtraInfo"] is ctypes.c_size_t


def test_send_input_text_converts_newlines_to_enter_keys() -> None:
    backend = object.__new__(SendInputBackend)
    recorded: list[_Input] = []
    backend._send = recorded.extend

    backend.type_text("A\r\nB\n")

    assert [(item.ki.wVk, item.ki.wScan, item.ki.dwFlags) for item in recorded] == [
        (0, ord("A"), 0x0004),
        (0, ord("A"), 0x0006),
        (0x0D, 0, 0),
        (0x0D, 0, 0x0002),
        (0, ord("B"), 0x0004),
        (0, ord("B"), 0x0006),
        (0x0D, 0, 0),
        (0x0D, 0, 0x0002),
    ]
