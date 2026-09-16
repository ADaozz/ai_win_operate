import os
import time
from collections.abc import Callable

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PIL import Image

from app.actions.executor import ActionExecutor
from app.actions.schema import parse_decision
from app.actions.validator import ActionValidator
from app.agent.runtime import AgentRuntime, RuntimeEvent
from app.agent.state import AgentState, AgentStatus
from app.ui.main_window import MainWindow
from app.windows.models import WindowInfo


class SingleWindowProvider:
    def __init__(self) -> None:
        self.window = WindowInfo(
            hwnd=123,
            title="Test Window",
            pid=456,
            left=10,
            top=20,
            width=800,
            height=600,
        )

    def list_windows(self) -> list[WindowInfo]:
        return [self.window]

    def exists(self, hwnd: int) -> bool:
        return hwnd == self.window.hwnd

    def get_window(self, hwnd: int) -> WindowInfo:
        assert hwnd == self.window.hwnd
        return self.window

    def is_minimized(self, hwnd: int) -> bool:
        assert hwnd == self.window.hwnd
        return False


class SingleFrameCapture:
    def capture(self, hwnd: int) -> Image.Image:
        assert hwnd == 123
        return Image.new("RGB", (400, 300), "navy")


class FinishClient:
    async def decide(self, observation: object, screenshot: Image.Image) -> object:
        del observation, screenshot
        return parse_decision(
            {
                "decision_summary": "线程任务可直接完成。",
                "actions": [{"type": "finish", "result": "线程任务完成"}],
            }
        )


class UnusedInputExecutor:
    pass


class FinishRuntimeFactory:
    def __init__(self, manager: SingleWindowProvider, capture: SingleFrameCapture) -> None:
        self.manager = manager
        self.capture = capture

    def create(
        self,
        task: str,
        hwnd: int,
        on_event: Callable[[RuntimeEvent], None] | None = None,
        on_frame: Callable[[Image.Image], None] | None = None,
    ) -> AgentRuntime:
        return AgentRuntime(
            AgentState(task=task, hwnd=hwnd),
            self.manager,
            self.capture,
            FinishClient(),  # type: ignore[arg-type]
            ActionValidator(self.manager),
            ActionExecutor(UnusedInputExecutor()),  # type: ignore[arg-type]
            action_delay_ms=0,
            on_event=on_event,
            on_frame=on_frame,
        )


def test_main_window_has_expected_shell() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow("Test Agent", SingleWindowProvider(), SingleFrameCapture())

    assert window.windowTitle() == "Test Agent"
    assert window.window_picker.selected_window is not None
    assert window.window_picker.selected_window.hwnd == 123
    assert window.screenshot_panel.target_hwnd == 123
    assert window.screenshot_panel.current_image is not None
    assert "已截图：HWND 123" in window.statusBar().currentMessage()
    assert window.agent_control.task_input.placeholderText().startswith("输入要让 AI")
    assert not window.agent_control.start_button.isEnabled()
    assert window.debug_group.isCheckable()
    assert not window.debug_group.isChecked()
    assert window.debug_panel.isHidden()

    window.debug_group.setChecked(True)
    assert not window.debug_panel.isHidden()

    window.screenshot_panel.clear_target_window()
    window.close()
    app.processEvents()


def test_main_window_runs_agent_on_qthread_without_blocking_ui() -> None:
    app = QApplication.instance() or QApplication([])
    manager = SingleWindowProvider()
    capture = SingleFrameCapture()
    factory = FinishRuntimeFactory(manager, capture)
    window = MainWindow(
        "Test Agent",
        manager,
        capture,
        runtime_factory=factory,
    )
    window.agent_control.task_input.setPlainText("完成线程测试")

    window.agent_control.start_button.click()
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        app.processEvents()
        if window._agent_thread is None:
            break
        time.sleep(0.01)

    assert window.agent_control.start_button.isEnabled()
    assert "线程任务完成" in window.statusBar().currentMessage()
    assert "决策" in window.agent_log.output.toPlainText()
    assert window._agent_thread is None
    window.close()
    app.processEvents()
