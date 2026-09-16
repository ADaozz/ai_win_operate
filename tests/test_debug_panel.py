from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.ui.debug_panel import ActionDebugPanel


class RecordingInputService:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def click(self, hwnd: int, x: float, y: float, **kwargs: object) -> None:
        self.calls.append(("click", hwnd, x, y, kwargs))

    def double_click(self, hwnd: int, x: float, y: float) -> None:
        self.calls.append(("double_click", hwnd, x, y))

    def right_click(self, hwnd: int, x: float, y: float) -> None:
        self.calls.append(("right_click", hwnd, x, y))

    def type_text(self, hwnd: int, text: str) -> None:
        self.calls.append(("type", hwnd, text))

    def hotkey(self, hwnd: int, keys: list[str]) -> None:
        self.calls.append(("hotkey", hwnd, keys))

    def scroll(self, hwnd: int, direction: str, amount: int = 3) -> None:
        self.calls.append(("scroll", hwnd, direction, amount))


def test_debug_panel_executes_selected_actions() -> None:
    app = QApplication.instance() or QApplication([])
    service = RecordingInputService()
    panel = ActionDebugPanel(service)
    panel.set_target_window(42)
    panel.x_input.setValue(0.25)
    panel.y_input.setValue(0.75)

    assert panel.execute_selected() is True
    assert service.calls[-1] == ("click", 42, 0.25, 0.75, {})

    panel.action_input.setCurrentIndex(panel.action_input.findData("hotkey"))
    panel.payload_input.setText("CTRL + A")
    assert panel.execute_selected() is True
    assert service.calls[-1] == ("hotkey", 42, ["CTRL", "A"])

    panel.action_input.setCurrentIndex(panel.action_input.findData("scroll_down"))
    panel.amount_input.setValue(4)
    assert panel.execute_selected() is True
    assert service.calls[-1] == ("scroll", 42, "down", 4)

    panel.close()
    app.processEvents()


def test_debug_panel_disables_execution_without_target() -> None:
    app = QApplication.instance() or QApplication([])
    panel = ActionDebugPanel(RecordingInputService())

    assert not panel.execute_button.isEnabled()
    assert panel.execute_selected() is False

    panel.close()
    app.processEvents()
