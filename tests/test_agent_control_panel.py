from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.agent.runtime import RuntimeEvent, RuntimePhase
from app.agent.state import AgentState, AgentStatus
from app.actions.schema import parse_action
from app.ui.agent_control_panel import AgentControlPanel
from app.ui.log_panel import AgentLogPanel


def test_agent_controls_require_task_target_and_runtime() -> None:
    app = QApplication.instance() or QApplication([])
    panel = AgentControlPanel()

    panel.set_target_available(True)
    panel.set_runtime_available(True)
    assert not panel.start_button.isEnabled()

    panel.task_input.setPlainText("点击文件菜单")
    assert panel.start_button.isEnabled()

    started: list[str] = []
    panel.start_requested.connect(started.append)
    panel.start_button.click()
    assert started == ["点击文件菜单"]

    panel.set_status(AgentStatus.RUNNING)
    assert not panel.start_button.isEnabled()
    assert panel.pause_button.isEnabled()
    assert panel.stop_button.isEnabled()
    assert not panel.task_input.isEnabled()

    panel.set_status(AgentStatus.PAUSED)
    assert panel.pause_button.text() == "继续"

    panel.set_status(AgentStatus.FINISHED)
    assert panel.start_button.isEnabled()
    assert panel.task_input.isEnabled()
    panel.close()
    app.processEvents()


def test_agent_controls_show_action_details_and_final_conclusion() -> None:
    app = QApplication.instance() or QApplication([])
    panel = AgentControlPanel()

    panel.update_runtime_event(
        RuntimeEvent(
            phase=RuntimePhase.DECIDE,
            status=AgentStatus.RUNNING,
            step=2,
            max_steps=30,
            action_type="click",
            action_detail="单击 x=0.900, y=0.100, 左键",
            decision_summary="需要先打开收藏夹入口。",
            message="已获取并校验模型动作",
        )
    )

    assert panel.runtime_status_label.text() == "运行中"
    assert panel.runtime_step_label.text() == "2 / 30"
    assert "x=0.900" in panel.runtime_action_label.text()
    assert panel.runtime_decision_label.text() == "需要先打开收藏夹入口。"
    assert "进行中" in panel.runtime_result_label.text()

    panel.show_final_state(
        AgentState(
            task="打开收藏夹",
            hwnd=123,
            status=AgentStatus.FAILED,
            step=5,
            last_action=parse_action(
                {
                    "type": "click",
                    "x": 0.9,
                    "y": 0.1,
                    "decision_summary": "收藏夹入口没有响应。",
                }
            ),
            message="连续重复动作达到安全上限",
        )
    )

    assert panel.runtime_status_label.text() == "执行失败"
    assert "重复动作" in panel.runtime_result_label.text()
    assert "x=0.900" in panel.runtime_action_label.text()
    assert panel.runtime_decision_label.text() == "收藏夹入口没有响应。"
    panel.close()
    app.processEvents()


def test_agent_log_shows_public_decision_summary() -> None:
    app = QApplication.instance() or QApplication([])
    panel = AgentLogPanel()
    panel.append_event(
        RuntimeEvent(
            phase=RuntimePhase.DECIDE,
            status=AgentStatus.RUNNING,
            step=4,
            max_steps=30,
            action_type="scroll",
            action_detail="向下滚动 3 格",
            decision_summary="当前内容没有显示完整，先检查下方信息。",
            message="已获取并校验模型动作",
        )
    )

    text = panel.output.toPlainText()
    assert "向下滚动 3 格" in text
    assert "决策说明：当前内容没有显示完整" in text
    panel.close()
    app.processEvents()
