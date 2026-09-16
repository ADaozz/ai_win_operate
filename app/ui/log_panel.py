"""In-memory, user-facing Agent Runtime event log."""

from __future__ import annotations

from PySide6.QtWidgets import QPlainTextEdit, QVBoxLayout, QWidget

from app.agent.runtime import RuntimeEvent, RuntimePhase

_PHASE_LABELS = {
    RuntimePhase.STATUS: "状态",
    RuntimePhase.OBSERVE: "观察",
    RuntimePhase.DECIDE: "决策",
    RuntimePhase.VALIDATE: "验证",
    RuntimePhase.EXECUTE: "执行",
    RuntimePhase.VERIFY: "校验",
    RuntimePhase.BLOCKED: "拦截",
}


class AgentLogPanel(QWidget):
    """Show safe step metadata without request bodies or screenshot data."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.output = QPlainTextEdit(self)
        self.output.setReadOnly(True)
        self.output.setPlaceholderText("Agent 运行记录将显示在这里")
        self.output.document().setMaximumBlockCount(500)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.output)

    def append_event(self, event: RuntimeEvent) -> None:
        phase = _PHASE_LABELS[event.phase]
        step = min(event.step, event.max_steps)
        action = f" · {event.action_detail}" if event.action_detail else ""
        self.output.appendPlainText(
            f"步骤 {step}/{event.max_steps} · {phase}{action} · {event.message}"
        )
        if event.phase is RuntimePhase.DECIDE and event.decision_summary:
            self.output.appendPlainText(f"  决策说明：{event.decision_summary}")

    def clear(self) -> None:
        self.output.clear()
