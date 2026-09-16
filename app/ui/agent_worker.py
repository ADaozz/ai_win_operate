"""Run Agent Runtime on a QThread without blocking the Qt event loop."""

from __future__ import annotations

import asyncio

from PySide6.QtCore import QObject, Signal, Slot

from app.agent.runtime import AgentRuntime
from app.agent.state import AgentState
from app.common.logging import get_logger

logger = get_logger(__name__)


class AgentWorker(QObject):
    completed = Signal(object)

    def __init__(
        self,
        runtime: AgentRuntime,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.runtime = runtime

    @Slot()
    def run(self) -> None:
        state: AgentState

        async def run_and_close() -> AgentState:
            try:
                return await self.runtime.run()
            finally:
                await self.runtime.aclose()

        try:
            state = asyncio.run(run_and_close())
        except Exception as exc:
            logger.exception(
                "agent_worker_failed",
                error_type=type(exc).__name__,
            )
            state = self.runtime.state
        self.completed.emit(state)
