"""Enumeration and inspection of top-level Windows desktop windows."""

from __future__ import annotations

import ctypes
import os
import sys
from ctypes import wintypes
from pathlib import Path
from typing import Protocol

from app.common.exceptions import (
    UnsupportedPlatformError,
    WindowNotFoundError,
    WindowOperationError,
)
from app.common.logging import get_logger
from app.windows.models import WindowInfo

logger = get_logger(__name__)
DEFAULT_BLOCKED_TARGET_PROCESSES = frozenset(("textinputhost.exe", "tabtip.exe"))


class Win32Backend(Protocol):
    """Small pywin32 surface used by :class:`WindowManager`."""

    def enum_windows(self) -> list[int]: ...

    def is_window(self, hwnd: int) -> bool: ...

    def is_visible(self, hwnd: int) -> bool: ...

    def is_minimized(self, hwnd: int) -> bool: ...

    def is_system_window(self, hwnd: int) -> bool: ...

    def get_title(self, hwnd: int) -> str: ...

    def get_pid(self, hwnd: int) -> int: ...

    def get_process_name(self, hwnd: int) -> str: ...

    def get_rect(self, hwnd: int) -> tuple[int, int, int, int]: ...

    def restore(self, hwnd: int) -> None: ...

    def set_foreground(self, hwnd: int) -> None: ...


class PyWin32Backend:
    """Production backend that lazily imports pywin32 on Windows."""

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise UnsupportedPlatformError(
                "Window enumeration is available only on Windows"
            )

        import win32api  # type: ignore[import-not-found]
        import win32con  # type: ignore[import-not-found]
        import win32gui  # type: ignore[import-not-found]
        import win32process  # type: ignore[import-not-found]

        self._api = win32api
        self._con = win32con
        self._gui = win32gui
        self._process = win32process
        self._get_shell_window = ctypes.windll.user32.GetShellWindow  # type: ignore[attr-defined]
        self._get_shell_window.argtypes = []
        self._get_shell_window.restype = wintypes.HWND

    def enum_windows(self) -> list[int]:
        handles: list[int] = []
        self._gui.EnumWindows(lambda hwnd, _: handles.append(hwnd), None)
        return handles

    def is_window(self, hwnd: int) -> bool:
        return bool(self._gui.IsWindow(hwnd))

    def is_visible(self, hwnd: int) -> bool:
        return bool(self._gui.IsWindowVisible(hwnd))

    def is_minimized(self, hwnd: int) -> bool:
        return bool(self._gui.IsIconic(hwnd))

    def is_system_window(self, hwnd: int) -> bool:
        shell_window = self._get_shell_window()
        if shell_window and hwnd == int(shell_window):
            return True
        extended_style = self._gui.GetWindowLong(hwnd, self._con.GWL_EXSTYLE)
        return bool(extended_style & self._con.WS_EX_TOOLWINDOW)

    def get_title(self, hwnd: int) -> str:
        return str(self._gui.GetWindowText(hwnd))

    def get_pid(self, hwnd: int) -> int:
        _, pid = self._process.GetWindowThreadProcessId(hwnd)
        return int(pid)

    def get_process_name(self, hwnd: int) -> str:
        pid = self.get_pid(hwnd)
        handle = None
        try:
            handle = self._api.OpenProcess(
                self._con.PROCESS_QUERY_INFORMATION | self._con.PROCESS_VM_READ,
                False,
                pid,
            )
            executable = self._process.GetModuleFileNameEx(handle, 0)
            return Path(str(executable)).name.casefold()
        except Exception:
            return ""
        finally:
            if handle is not None:
                handle.Close()

    def get_rect(self, hwnd: int) -> tuple[int, int, int, int]:
        left, top, right, bottom = self._gui.GetWindowRect(hwnd)
        return int(left), int(top), int(right), int(bottom)

    def restore(self, hwnd: int) -> None:
        self._gui.ShowWindow(hwnd, self._con.SW_RESTORE)

    def set_foreground(self, hwnd: int) -> None:
        foreground = int(self._gui.GetForegroundWindow() or 0)
        if foreground == hwnd:
            return

        current_thread = int(self._api.GetCurrentThreadId())
        thread_ids: list[int] = []
        if foreground:
            foreground_thread, _ = self._process.GetWindowThreadProcessId(foreground)
            thread_ids.append(int(foreground_thread))
        target_thread, _ = self._process.GetWindowThreadProcessId(hwnd)
        thread_ids.append(int(target_thread))

        attached: list[int] = []
        try:
            for thread_id in dict.fromkeys(thread_ids):
                if thread_id and thread_id != current_thread:
                    self._process.AttachThreadInput(current_thread, thread_id, True)
                    attached.append(thread_id)
            self._gui.BringWindowToTop(hwnd)
            self._gui.SetForegroundWindow(hwnd)
        finally:
            for thread_id in reversed(attached):
                self._process.AttachThreadInput(current_thread, thread_id, False)


class WindowManager:
    """Expose safe, typed operations for top-level windows."""

    def __init__(
        self,
        backend: Win32Backend | None = None,
        *,
        minimum_width: int = 100,
        minimum_height: int = 60,
        current_process_id: int | None = None,
        blocked_process_names: frozenset[str] = DEFAULT_BLOCKED_TARGET_PROCESSES,
    ) -> None:
        if minimum_width <= 0 or minimum_height <= 0:
            raise ValueError("Minimum window dimensions must be positive")
        self._backend = backend or PyWin32Backend()
        self._minimum_width = minimum_width
        self._minimum_height = minimum_height
        self._current_process_id = current_process_id or os.getpid()
        self._blocked_process_names = frozenset(
            name.casefold() for name in blocked_process_names
        )

    def list_windows(self) -> list[WindowInfo]:
        """Return visible, titled, useful top-level windows."""
        windows: list[WindowInfo] = []
        for hwnd in self._backend.enum_windows():
            try:
                if not self._is_candidate(hwnd):
                    continue
                rect = self._backend.get_rect(hwnd)
                width = rect[2] - rect[0]
                height = rect[3] - rect[1]
                if (
                    width < self._minimum_width
                    or height < self._minimum_height
                ):
                    continue
                window = self._read_window(hwnd, rect)
                windows.append(window)
            except Exception as exc:
                logger.warning(
                    "window_enumeration_skipped",
                    hwnd=hwnd,
                    error=str(exc),
                )
        return sorted(windows, key=lambda item: (item.title.casefold(), item.hwnd))

    def get_window(self, hwnd: int) -> WindowInfo:
        """Read current information for an HWND."""
        if not self.exists(hwnd):
            raise WindowNotFoundError(f"Window no longer exists: HWND {hwnd}")
        try:
            return self._read_window(hwnd)
        except Exception as exc:
            raise WindowOperationError(
                f"Unable to inspect window: HWND {hwnd}"
            ) from exc

    def exists(self, hwnd: int) -> bool:
        """Return whether *hwnd* currently identifies a window."""
        if hwnd <= 0:
            return False
        try:
            return self._backend.is_window(hwnd)
        except Exception as exc:
            logger.warning("window_exists_check_failed", hwnd=hwnd, error=str(exc))
            return False

    def is_minimized(self, hwnd: int) -> bool:
        """Return whether the target window is minimized."""
        if not self.exists(hwnd):
            raise WindowNotFoundError(f"Window no longer exists: HWND {hwnd}")
        try:
            return self._backend.is_minimized(hwnd)
        except Exception as exc:
            raise WindowOperationError(
                f"Unable to read minimized state: HWND {hwnd}"
            ) from exc

    def get_process_name(self, hwnd: int) -> str:
        """Return the executable file name for *hwnd*."""
        if not self.exists(hwnd):
            raise WindowNotFoundError(f"Window no longer exists: HWND {hwnd}")
        try:
            return self._backend.get_process_name(hwnd)
        except Exception as exc:
            raise WindowOperationError(
                f"Unable to read process name: HWND {hwnd}"
            ) from exc

    def focus(self, hwnd: int) -> None:
        """Restore a minimized window and request foreground focus."""
        if not self.exists(hwnd):
            raise WindowNotFoundError(f"Window no longer exists: HWND {hwnd}")
        try:
            if self._backend.is_minimized(hwnd):
                self._backend.restore(hwnd)
            self._backend.set_foreground(hwnd)
        except Exception as exc:
            raise WindowOperationError(f"Unable to focus window: HWND {hwnd}") from exc

    def _is_candidate(self, hwnd: int) -> bool:
        if (
            not self._backend.is_window(hwnd)
            or not self._backend.is_visible(hwnd)
            or self._backend.is_system_window(hwnd)
            or not self._backend.get_title(hwnd).strip()
        ):
            return False
        if self._backend.get_pid(hwnd) == self._current_process_id:
            return False
        return self._backend.get_process_name(hwnd).casefold() not in (
            self._blocked_process_names
        )

    def _read_window(
        self,
        hwnd: int,
        rect: tuple[int, int, int, int] | None = None,
    ) -> WindowInfo:
        left, top, right, bottom = rect or self._backend.get_rect(hwnd)
        return WindowInfo(
            hwnd=hwnd,
            title=self._backend.get_title(hwnd).strip(),
            pid=self._backend.get_pid(hwnd),
            left=left,
            top=top,
            width=right - left,
            height=bottom - top,
        )
