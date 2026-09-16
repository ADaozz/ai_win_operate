"""Task entry and Start/Pause/Resume/Stop controls."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.actions.presentation import describe_action, describe_decision
from app.agent.runtime import RuntimeEvent
from app.agent.state import AgentState
from app.agent.state import AgentStatus, TERMINAL_STATUSES

_STATUS_LABELS = {
    AgentStatus.IDLE: "准备就绪",
    AgentStatus.RUNNING: "运行中",
    AgentStatus.PAUSED: "已暂停",
    AgentStatus.FINISHED: "已完成",
    AgentStatus.FAILED: "执行失败",
    AgentStatus.STOPPED: "已停止",
}

_STATUS_COLORS = {
    AgentStatus.IDLE: "#555555",
    AgentStatus.RUNNING: "#1565c0",
    AgentStatus.PAUSED: "#ef6c00",
    AgentStatus.FINISHED: "#2e7d32",
    AgentStatus.FAILED: "#c62828",
    AgentStatus.STOPPED: "#616161",
}


class AgentControlPanel(QWidget):
    start_requested = Signal(str)
    pause_requested = Signal()
    resume_requested = Signal()
    stop_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._target_available = False
        self._runtime_available = False
        self._status = AgentStatus.IDLE

        self.task_input = QPlainTextEdit(self)
        self.task_input.setPlaceholderText(
            "输入要让 AI 在目标窗口中完成的任务，例如：点击文件菜单"
        )
        self.task_input.setMaximumHeight(88)

        self.start_button = QPushButton("开始", self)
        self.pause_button = QPushButton("暂停", self)
        self.stop_button = QPushButton("停止", self)
        self.shortcut_label = QLabel("F8：紧急停止", self)

        summary = QFrame(self)
        summary.setFrameShape(QFrame.Shape.StyledPanel)
        summary_layout = QGridLayout(summary)
        self.runtime_status_label = QLabel("准备就绪", summary)
        self.runtime_step_label = QLabel("0 / 30", summary)
        self.runtime_action_label = QLabel("尚未获取模型动作", summary)
        self.runtime_decision_label = QLabel("等待模型决策说明", summary)
        self.runtime_result_label = QLabel("等待开始任务", summary)
        for label in (
            self.runtime_status_label,
            self.runtime_step_label,
            self.runtime_action_label,
            self.runtime_decision_label,
            self.runtime_result_label,
        ):
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setWordWrap(True)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.runtime_status_label.setStyleSheet(
            "font-weight: 700; color: #555555;"
        )
        self.runtime_result_label.setStyleSheet("font-weight: 600;")
        summary_layout.addWidget(QLabel("当前状态", summary), 0, 0)
        summary_layout.addWidget(self.runtime_status_label, 0, 1)
        summary_layout.addWidget(QLabel("执行步骤", summary), 0, 2)
        summary_layout.addWidget(self.runtime_step_label, 0, 3)
        summary_layout.addWidget(QLabel("最近动作", summary), 1, 0)
        summary_layout.addWidget(self.runtime_action_label, 1, 1, 1, 3)
        summary_layout.addWidget(QLabel("决策说明", summary), 2, 0)
        summary_layout.addWidget(self.runtime_decision_label, 2, 1, 1, 3)
        summary_layout.addWidget(QLabel("最终结论", summary), 3, 0)
        summary_layout.addWidget(self.runtime_result_label, 3, 1, 1, 3)
        summary_layout.setColumnStretch(1, 2)
        summary_layout.setColumnStretch(3, 1)

        buttons = QHBoxLayout()
        buttons.addWidget(self.start_button)
        buttons.addWidget(self.pause_button)
        buttons.addWidget(self.stop_button)
        buttons.addStretch(1)
        buttons.addWidget(self.shortcut_label)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.task_input)
        layout.addLayout(buttons)
        layout.addWidget(summary)

        self.task_input.textChanged.connect(self._update_buttons)
        self.start_button.clicked.connect(self._request_start)
        self.pause_button.clicked.connect(self._request_pause_or_resume)
        self.stop_button.clicked.connect(self.stop_requested.emit)
        self._update_buttons()

    @property
    def task(self) -> str:
        return self.task_input.toPlainText().strip()

    def set_target_available(self, available: bool) -> None:
        self._target_available = available
        self._update_buttons()

    def set_runtime_available(self, available: bool) -> None:
        self._runtime_available = available
        self._update_buttons()

    def set_status(self, status: AgentStatus) -> None:
        self._status = status
        self.pause_button.setText("继续" if status is AgentStatus.PAUSED else "暂停")
        active = status in (AgentStatus.RUNNING, AgentStatus.PAUSED)
        self.task_input.setEnabled(not active)
        self.runtime_status_label.setText(_STATUS_LABELS[status])
        self.runtime_status_label.setStyleSheet(
            f"font-weight: 700; color: {_STATUS_COLORS[status]};"
        )
        self._update_buttons()

    def reset_runtime_display(self, max_steps: int = 30) -> None:
        self.runtime_step_label.setText(f"0 / {max_steps}")
        self.runtime_action_label.setText("尚未获取模型动作")
        self.runtime_decision_label.setText("等待模型决策说明")
        self.runtime_result_label.setText("任务运行中，等待最终结论")

    def update_runtime_event(self, event: RuntimeEvent) -> None:
        self.set_status(event.status)
        self.runtime_step_label.setText(f"{event.step} / {event.max_steps}")
        if event.action_detail:
            self.runtime_action_label.setText(event.action_detail)
        if event.decision_summary:
            self.runtime_decision_label.setText(event.decision_summary)
        if event.status in TERMINAL_STATUSES or event.phase.value == "blocked":
            self.runtime_result_label.setText(
                f"{_STATUS_LABELS[event.status]}：{event.message}"
            )
        elif event.phase.value in (
            "observe",
            "decide",
            "validate",
            "execute",
            "verify",
        ):
            self.runtime_result_label.setText(f"进行中：{event.message}")

    def show_final_state(self, state: AgentState) -> None:
        self.set_status(state.status)
        self.runtime_step_label.setText(f"{state.step} / {state.max_steps}")
        self.runtime_action_label.setText(describe_action(state.last_action))
        self.runtime_decision_label.setText(describe_decision(state.last_action))
        self.runtime_result_label.setText(
            f"{_STATUS_LABELS[state.status]}：{state.message}"
        )

    def _request_start(self) -> None:
        task = self.task
        if task:
            self.start_requested.emit(task)

    def _request_pause_or_resume(self) -> None:
        if self._status is AgentStatus.PAUSED:
            self.resume_requested.emit()
        elif self._status is AgentStatus.RUNNING:
            self.pause_requested.emit()

    def _update_buttons(self) -> None:
        active = self._status in (AgentStatus.RUNNING, AgentStatus.PAUSED)
        can_start = (
            not active
            and self._status in TERMINAL_STATUSES.union((AgentStatus.IDLE,))
            and self._target_available
            and self._runtime_available
            and bool(self.task)
        )
        self.start_button.setEnabled(can_start)
        self.pause_button.setEnabled(active)
        self.stop_button.setEnabled(active)
