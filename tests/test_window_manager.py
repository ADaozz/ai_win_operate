from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.common.exceptions import WindowNotFoundError
from app.windows.window_manager import PyWin32Backend, WindowManager


@dataclass
class FakeWindow:
    title: str
    pid: int
    rect: tuple[int, int, int, int]
    visible: bool = True
    system: bool = False
    minimized: bool = False
    process_name: str = "application.exe"


class FakeBackend:
    def __init__(self, windows: dict[int, FakeWindow]) -> None:
        self.windows = windows
        self.restored: list[int] = []
        self.focused: list[int] = []

    def enum_windows(self) -> list[int]:
        return list(self.windows)

    def is_window(self, hwnd: int) -> bool:
        return hwnd in self.windows

    def is_visible(self, hwnd: int) -> bool:
        return self.windows[hwnd].visible

    def is_minimized(self, hwnd: int) -> bool:
        return self.windows[hwnd].minimized

    def is_system_window(self, hwnd: int) -> bool:
        return self.windows[hwnd].system

    def get_title(self, hwnd: int) -> str:
        return self.windows[hwnd].title

    def get_pid(self, hwnd: int) -> int:
        return self.windows[hwnd].pid

    def get_process_name(self, hwnd: int) -> str:
        return self.windows[hwnd].process_name

    def get_rect(self, hwnd: int) -> tuple[int, int, int, int]:
        return self.windows[hwnd].rect

    def restore(self, hwnd: int) -> None:
        self.restored.append(hwnd)
        self.windows[hwnd].minimized = False

    def set_foreground(self, hwnd: int) -> None:
        self.focused.append(hwnd)


def test_pywin32_backend_uses_user32_for_shell_window() -> None:
    class FakeGui:
        @staticmethod
        def GetWindowLong(hwnd: int, index: int) -> int:
            assert index == -20
            return 0x80 if hwnd == 30 else 0

    backend = object.__new__(PyWin32Backend)
    backend._gui = FakeGui()
    backend._con = type("FakeCon", (), {"GWL_EXSTYLE": -20, "WS_EX_TOOLWINDOW": 0x80})()
    backend._get_shell_window = lambda: 10

    assert backend.is_system_window(10) is True
    assert backend.is_system_window(20) is False
    assert backend.is_system_window(30) is True


def test_pywin32_backend_attaches_input_threads_for_foreground_focus() -> None:
    class FakeGui:
        foreground = 10
        brought: list[int] = []
        focused: list[int] = []

        @classmethod
        def GetForegroundWindow(cls) -> int:
            return cls.foreground

        @classmethod
        def BringWindowToTop(cls, hwnd: int) -> None:
            cls.brought.append(hwnd)

        @classmethod
        def SetForegroundWindow(cls, hwnd: int) -> None:
            cls.focused.append(hwnd)

    class FakeProcess:
        attached: list[tuple[int, int, bool]] = []

        @staticmethod
        def GetWindowThreadProcessId(hwnd: int) -> tuple[int, int]:
            return ({10: 200, 20: 300}[hwnd], 1)

        @classmethod
        def AttachThreadInput(cls, source: int, target: int, attach: bool) -> None:
            cls.attached.append((source, target, attach))

    backend = object.__new__(PyWin32Backend)
    backend._api = type("FakeApi", (), {"GetCurrentThreadId": lambda self: 100})()
    backend._gui = FakeGui()
    backend._process = FakeProcess()

    backend.set_foreground(20)

    assert FakeGui.brought == [20]
    assert FakeGui.focused == [20]
    assert FakeProcess.attached == [
        (100, 200, True),
        (100, 300, True),
        (100, 300, False),
        (100, 200, False),
    ]


def test_list_windows_filters_and_sorts_candidates() -> None:
    backend = FakeBackend(
        {
            10: FakeWindow("Zulu", 100, (20, 30, 1220, 830)),
            11: FakeWindow("  alpha  ", 101, (-100, 40, 900, 740)),
            12: FakeWindow("Hidden", 102, (0, 0, 800, 600), visible=False),
            13: FakeWindow("   ", 103, (0, 0, 800, 600)),
            14: FakeWindow("Tool", 104, (0, 0, 800, 600), system=True),
            15: FakeWindow("Tiny", 105, (0, 0, 99, 59)),
            16: FakeWindow("Zero size", 106, (20, 20, 20, 20)),
        }
    )

    windows = WindowManager(backend).list_windows()

    assert [window.hwnd for window in windows] == [11, 10]
    assert windows[0].title == "alpha"
    assert windows[0].left == -100
    assert windows[0].width == 1000
    assert windows[0].height == 700


def test_list_windows_excludes_agent_and_system_input_surfaces() -> None:
    backend = FakeBackend(
        {
            17: FakeWindow(
                "Windows 输入体验",
                700,
                (0, 0, 1200, 800),
                process_name="TextInputHost.exe",
            ),
            18: FakeWindow(
                "Windows GUI 智能助手",
                999,
                (0, 0, 1200, 800),
                process_name="python.exe",
            ),
            19: FakeWindow(
                "Notepad",
                701,
                (0, 0, 1200, 800),
                process_name="notepad.exe",
            ),
        }
    )

    windows = WindowManager(backend, current_process_id=999).list_windows()

    assert [window.hwnd for window in windows] == [19]


def test_get_window_reads_current_rect_and_detects_disappearance() -> None:
    backend = FakeBackend({21: FakeWindow("Editor", 300, (10, 20, 810, 620))})
    manager = WindowManager(backend)

    assert manager.get_window(21).model_dump() == {
        "hwnd": 21,
        "title": "Editor",
        "pid": 300,
        "left": 10,
        "top": 20,
        "width": 800,
        "height": 600,
    }

    backend.windows[21].rect = (30, 40, 1030, 840)
    assert manager.get_window(21).left == 30

    del backend.windows[21]
    assert manager.exists(21) is False
    with pytest.raises(WindowNotFoundError, match="21"):
        manager.get_window(21)


def test_focus_restores_minimized_window_before_foregrounding() -> None:
    backend = FakeBackend(
        {31: FakeWindow("Notepad", 400, (0, 0, 800, 600), minimized=True)}
    )
    manager = WindowManager(backend)

    assert manager.is_minimized(31) is True
    manager.focus(31)

    assert backend.restored == [31]
    assert backend.focused == [31]
    assert manager.is_minimized(31) is False


def test_invalid_minimum_dimensions_are_rejected() -> None:
    with pytest.raises(ValueError, match="positive"):
        WindowManager(FakeBackend({}), minimum_width=0)
