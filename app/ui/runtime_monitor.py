"""Non-activating, click-through, always-on-top Runtime status monitor."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from app.actions.presentation import describe_action, describe_decision
from app.agent.runtime import RuntimeEvent
from app.agent.state import AgentState, AgentStatus, TERMINAL_STATUSES

_STATUS_LABELS = {
    AgentStatus.IDLE: "准备就绪",
    AgentStatus.RUNNING: "运行中",
    AgentStatus.PAUSED: "已暂停",
    AgentStatus.FINISHED: "已完成",
    AgentStatus.FAILED: "执行失败",
    AgentStatus.STOPPED: "已停止",
}

_STATUS_COLORS = {
    AgentStatus.IDLE: "#dddddd",
    AgentStatus.RUNNING: "#64b5f6",
    AgentStatus.PAUSED: "#ffb74d",
    AgentStatus.FINISHED: "#81c784",
    AgentStatus.FAILED: "#ef5350",
    AgentStatus.STOPPED: "#bdbdbd",
}


class RuntimeMonitor(QWidget):
    """Expose progress without taking foreground focus from the target HWND."""

    def __init__(self, parent: QWidget | None = None) -> None:
        flags = (
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowTransparentForInput
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        super().__init__(parent, flags)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedWidth(460)

        container = QWidget(self)
        container.setObjectName("monitorContainer")
        container.setStyleSheet(
            "#monitorContainer {"
            "background: rgba(25, 25, 28, 235);"
            "border: 1px solid #666666;"
            "border-radius: 8px;"
            "}"
            "QLabel { color: #f2f2f2; }"
        )
        self.status_label = QLabel("准备就绪", container)
        self.step_label = QLabel("步骤 0/30", container)
        self.action_label = QLabel("最近动作：尚无", container)
        self.decision_label = QLabel("决策说明：等待模型", container)
        self.message_label = QLabel("F8：紧急停止", container)
        self.status_label.setStyleSheet("font-size: 16px; font-weight: 700;")
        self.action_label.setWordWrap(True)
        self.decision_label.setWordWrap(True)
        self.message_label.setWordWrap(True)
        for label in (
            self.status_label,
            self.step_label,
            self.action_label,
            self.decision_label,
            self.message_label,
        ):
            label.setTextFormat(Qt.TextFormat.PlainText)

        content = QVBoxLayout(container)
        content.setContentsMargins(14, 10, 14, 10)
        content.setSpacing(4)
        content.addWidget(self.status_label)
        content.addWidget(self.step_label)
        content.addWidget(self.action_label)
        content.addWidget(self.decision_label)
        content.addWidget(self.message_label)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(container)

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide)
        self._emergency_stop_available = True

    def set_emergency_stop_available(self, available: bool) -> None:
        self._emergency_stop_available = available

    def begin(self, max_steps: int = 30) -> None:
        self._hide_timer.stop()
        self._set_status(AgentStatus.RUNNING)
        self.step_label.setText(f"步骤 0/{max_steps}")
        self.action_label.setText("最近动作：等待模型决策")
        self.decision_label.setText("决策说明：等待模型")
        self.message_label.setText(
            "任务运行中 · F8：紧急停止"
            if self._emergency_stop_available
            else "任务运行中 · 请使用主界面的停止按钮"
        )
        self.adjustSize()
        self._move_to_top_right()
        self.show()
        self.raise_()

    def update_event(self, event: RuntimeEvent) -> None:
        self._set_status(event.status)
        self.step_label.setText(f"步骤 {event.step}/{event.max_steps}")
        if event.action_detail:
            self.action_label.setText(f"最近动作：{event.action_detail}")
        if event.decision_summary:
            self.decision_label.setText(f"决策说明：{event.decision_summary}")
        self.message_label.setText(event.message)
        self.adjustSize()
        self._move_to_top_right()
        if not self.isVisible():
            self.show()

    def show_final(self, state: AgentState, duration_ms: int = 12000) -> None:
        self._set_status(state.status)
        self.step_label.setText(f"步骤 {state.step}/{state.max_steps}")
        self.action_label.setText(f"最近动作：{describe_action(state.last_action)}")
        self.decision_label.setText(f"决策说明：{describe_decision(state.last_action)}")
        self.message_label.setText(
            f"最终结论：{_STATUS_LABELS[state.status]} · {state.message}"
        )
        self.adjustSize()
        self._move_to_top_right()
        self.show()
        self.raise_()
        if state.status in TERMINAL_STATUSES:
            self._hide_timer.start(duration_ms)

    def _set_status(self, status: AgentStatus) -> None:
        self.status_label.setText(_STATUS_LABELS[status])
        self.status_label.setStyleSheet(
            f"font-size: 16px; font-weight: 700; color: {_STATUS_COLORS[status]};"
        )

    def _move_to_top_right(self) -> None:
        screen = QGuiApplication.screenAt(self.pos()) or QGuiApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        self.move(area.right() - self.width() - 20, area.top() + 20)
