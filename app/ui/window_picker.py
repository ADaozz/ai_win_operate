"""Window selection widget backed by HWND identity."""

from __future__ import annotations

from typing import Protocol

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QPushButton, QWidget

from app.common.exceptions import WindowsGuiAgentError
from app.common.logging import get_logger
from app.windows.models import WindowInfo
from app.windows.window_manager import WindowManager

logger = get_logger(__name__)


class WindowProvider(Protocol):
    def list_windows(self) -> list[WindowInfo]: ...


class WindowPicker(QWidget):
    """List eligible windows and retain selection by HWND."""

    window_selected = Signal(int)
    selection_cleared = Signal()

    def __init__(
        self,
        window_manager: WindowProvider | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._window_manager = window_manager
        self._startup_error: str | None = None
        if self._window_manager is None:
            try:
                self._window_manager = WindowManager()
            except WindowsGuiAgentError as exc:
                self._startup_error = str(exc)
                logger.warning("window_manager_unavailable", error=str(exc))

        self.combo_box = QComboBox(self)
        self.combo_box.setMinimumContentsLength(45)
        self.refresh_button = QPushButton("刷新", self)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.combo_box, stretch=1)
        layout.addWidget(self.refresh_button)

        self.refresh_button.clicked.connect(self.refresh)
        self.combo_box.currentIndexChanged.connect(self._emit_selection)
        self.refresh()

    @property
    def window_manager(self) -> WindowProvider | None:
        """Return the provider used by this picker."""
        return self._window_manager

    @property
    def selected_window(self) -> WindowInfo | None:
        """Return the current WindowInfo snapshot, if one is selected."""
        data = self.combo_box.currentData()
        return data if isinstance(data, WindowInfo) else None

    def refresh(self) -> None:
        """Reload windows while preserving selection by HWND when possible."""
        selected = self.selected_window
        selected_hwnd = selected.hwnd if selected is not None else None

        self.combo_box.blockSignals(True)
        self.combo_box.clear()

        if self._window_manager is None:
            self._show_message(self._startup_error or "窗口管理器不可用")
            self.combo_box.blockSignals(False)
            return

        try:
            windows = self._window_manager.list_windows()
        except WindowsGuiAgentError as exc:
            logger.error("window_refresh_failed", error=str(exc))
            self._show_message(f"无法列出窗口：{exc}")
            self.combo_box.blockSignals(False)
            return
        except Exception as exc:
            logger.exception("unexpected_window_refresh_failure", error=str(exc))
            self._show_message("无法列出窗口")
            self.combo_box.blockSignals(False)
            return

        if not windows:
            self._show_message("未找到可用窗口")
        else:
            for window in windows:
                label = (
                    f"{window.title} — HWND {window.hwnd} "
                    f"({window.width}×{window.height})"
                )
                self.combo_box.addItem(label, window)

            if selected_hwnd is not None:
                for index in range(self.combo_box.count()):
                    window = self.combo_box.itemData(index)
                    if isinstance(window, WindowInfo) and window.hwnd == selected_hwnd:
                        self.combo_box.setCurrentIndex(index)
                        break

        self.combo_box.blockSignals(False)
        self._emit_selection(self.combo_box.currentIndex())

    def _show_message(self, message: str) -> None:
        self.combo_box.addItem(message, None)
        self.combo_box.setCurrentIndex(0)

    def _emit_selection(self, _index: int) -> None:
        window = self.selected_window
        if window is not None:
            self.window_selected.emit(window.hwnd)
        else:
            self.selection_cleared.emit()
