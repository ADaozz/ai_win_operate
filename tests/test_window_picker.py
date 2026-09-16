from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.ui.window_picker import WindowPicker
from app.windows.models import WindowInfo


def make_window(hwnd: int, title: str) -> WindowInfo:
    return WindowInfo(
        hwnd=hwnd,
        title=title,
        pid=100 + hwnd,
        left=0,
        top=0,
        width=800,
        height=600,
    )


class MutableWindowProvider:
    def __init__(self, windows: list[WindowInfo]) -> None:
        self.windows = windows

    def list_windows(self) -> list[WindowInfo]:
        return self.windows


def test_picker_lists_windows_and_preserves_hwnd_selection() -> None:
    app = QApplication.instance() or QApplication([])
    first = make_window(101, "Editor")
    second = make_window(202, "Calculator")
    provider = MutableWindowProvider([first, second])
    picker = WindowPicker(provider)
    selected_handles: list[int] = []
    picker.window_selected.connect(selected_handles.append)

    picker.combo_box.setCurrentIndex(1)
    assert picker.selected_window == second

    provider.windows = [second, first]
    picker.refresh()

    assert picker.selected_window is not None
    assert picker.selected_window.hwnd == 202
    assert "HWND 202" in picker.combo_box.currentText()
    assert selected_handles[-1] == 202

    cleared: list[bool] = []
    picker.selection_cleared.connect(lambda: cleared.append(True))
    provider.windows = []
    picker.refresh()
    assert cleared == [True]
    assert picker.selected_window is None

    picker.close()
    app.processEvents()


def test_picker_displays_empty_state() -> None:
    app = QApplication.instance() or QApplication([])
    picker = WindowPicker(MutableWindowProvider([]))

    assert picker.selected_window is None
    assert picker.combo_box.currentText() == "未找到可用窗口"

    picker.close()
    app.processEvents()
