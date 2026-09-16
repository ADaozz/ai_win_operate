from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from app.actions.schema import parse_action
from app.agent.runtime import RuntimeEvent, RuntimePhase
from app.agent.state import AgentState, AgentStatus
from app.ui.runtime_monitor import RuntimeMonitor


def test_runtime_monitor_is_topmost_nonactivating_and_click_through() -> None:
    app = QApplication.instance() or QApplication([])
    monitor = RuntimeMonitor()

    flags = monitor.windowFlags()
    assert flags & Qt.WindowType.WindowStaysOnTopHint
    assert flags & Qt.WindowType.WindowTransparentForInput
    assert flags & Qt.WindowType.WindowDoesNotAcceptFocus

    monitor.begin(30)
    monitor.update_event(
        RuntimeEvent(
            phase=RuntimePhase.DECIDE,
            status=AgentStatus.RUNNING,
            step=2,
            max_steps=30,
            action_type="click",
            action_detail="单击 x=0.500, y=0.100, 左键",
            decision_summary="页面内容未完整显示，先检查目标区域。",
            message="已获取并校验模型动作",
        )
    )
    assert monitor.status_label.text() == "运行中"
    assert monitor.step_label.text() == "步骤 2/30"
    assert "x=0.500" in monitor.action_label.text()
    assert "页面内容未完整显示" in monitor.decision_label.text()

    monitor.show_final(
        AgentState(
            task="测试",
            hwnd=123,
            status=AgentStatus.FINISHED,
            step=2,
            last_action=parse_action({"type": "finish", "result": "完成"}),
            message="完成",
        ),
        duration_ms=50,
    )
    assert "最终结论：已完成" in monitor.message_label.text()
    monitor.close()
    app.processEvents()
