"""Manual mouse and keyboard action panel for Milestone 3."""

from __future__ import annotations

from typing import Protocol

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QWidget,
)

from app.common.exceptions import WindowsGuiAgentError
from app.common.logging import get_logger

logger = get_logger(__name__)


class InputService(Protocol):
    def click(self, hwnd: int, x: float, y: float, **kwargs: object) -> None: ...

    def double_click(self, hwnd: int, x: float, y: float) -> None: ...

    def right_click(self, hwnd: int, x: float, y: float) -> None: ...

    def type_text(self, hwnd: int, text: str) -> None: ...

    def hotkey(self, hwnd: int, keys: list[str]) -> None: ...

    def scroll(self, hwnd: int, direction: str, amount: int = 3) -> None: ...


class ActionDebugPanel(QWidget):
    """Execute explicitly selected actions without involving an LLM."""

    status_changed = Signal(str)

    def __init__(
        self,
        input_service: InputService | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._input_service = input_service
        self._target_hwnd: int | None = None

        self.x_input = QDoubleSpinBox(self)
        self.x_input.setRange(0.0, 1.0)
        self.x_input.setDecimals(3)
        self.x_input.setSingleStep(0.05)
        self.x_input.setValue(0.5)

        self.y_input = QDoubleSpinBox(self)
        self.y_input.setRange(0.0, 1.0)
        self.y_input.setDecimals(3)
        self.y_input.setSingleStep(0.05)
        self.y_input.setValue(0.5)

        coordinates = QWidget(self)
        coordinate_layout = QHBoxLayout(coordinates)
        coordinate_layout.setContentsMargins(0, 0, 0, 0)
        coordinate_layout.addWidget(self.x_input)
        coordinate_layout.addWidget(self.y_input)

        self.action_input = QComboBox(self)
        for label, action in (
            ("单击", "click"),
            ("双击", "double_click"),
            ("右键单击", "right_click"),
            ("输入文本", "type"),
            ("组合键", "hotkey"),
            ("向上滚动", "scroll_up"),
            ("向下滚动", "scroll_down"),
        ):
            self.action_input.addItem(label, action)
        self.payload_input = QLineEdit(self)
        self.payload_input.setPlaceholderText("输入文本或组合键，例如 CTRL+A")
        self.amount_input = QSpinBox(self)
        self.amount_input.setRange(1, 20)
        self.amount_input.setValue(3)
        self.execute_button = QPushButton("执行", self)
        self.execute_button.setEnabled(False)

        layout = QFormLayout(self)
        layout.addRow("归一化坐标 x / y", coordinates)
        layout.addRow("动作", self.action_input)
        layout.addRow("文本 / 组合键", self.payload_input)
        layout.addRow("滚动量", self.amount_input)
        layout.addRow(self.execute_button)

        self.execute_button.clicked.connect(lambda: self.execute_selected())

    @property
    def target_hwnd(self) -> int | None:
        return self._target_hwnd

    def set_target_window(self, hwnd: int) -> None:
        self._target_hwnd = hwnd
        self.execute_button.setEnabled(self._input_service is not None)

    def clear_target_window(self) -> None:
        self._target_hwnd = None
        self.execute_button.setEnabled(False)

    def execute_selected(self) -> bool:
        """Execute the form action and report whether it succeeded."""
        if self._input_service is None or self._target_hwnd is None:
            self.status_changed.emit("输入功能不可用")
            return False

        action = self.action_input.currentData()
        if not isinstance(action, str):
            self.status_changed.emit("未选择有效动作")
            return False
        hwnd = self._target_hwnd
        x = self.x_input.value()
        y = self.y_input.value()
        try:
            if action == "click":
                self._input_service.click(hwnd, x, y)
            elif action == "double_click":
                self._input_service.double_click(hwnd, x, y)
            elif action == "right_click":
                self._input_service.right_click(hwnd, x, y)
            elif action == "type":
                self._input_service.type_text(hwnd, self.payload_input.text())
            elif action == "hotkey":
                keys = [part.strip() for part in self.payload_input.text().split("+")]
                keys = [key for key in keys if key]
                self._input_service.hotkey(hwnd, keys)
            elif action in ("scroll_up", "scroll_down"):
                direction = "up" if action == "scroll_up" else "down"
                self._input_service.scroll(hwnd, direction, self.amount_input.value())
            else:
                raise ValueError(f"Unknown debug action: {action}")
        except WindowsGuiAgentError as exc:
            logger.error(
                "debug_action_failed",
                hwnd=hwnd,
                action=action,
                error=str(exc),
            )
            self.status_changed.emit(f"输入失败 — {exc}")
            return False
        except Exception as exc:
            logger.exception(
                "unexpected_debug_action_failure",
                hwnd=hwnd,
                action=action,
                error=str(exc),
            )
            self.status_changed.emit("输入失败")
            return False

        logger.info("debug_action_executed", hwnd=hwnd, action=action)
        self.status_changed.emit(f"已执行：{self.action_input.currentText()} — HWND {hwnd}")
        return True
