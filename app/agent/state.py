"""Typed, serializable state for one Agent Runtime session."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from app.actions.schema import ActionResult, AgentAction


class AgentStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    FINISHED = "finished"
    FAILED = "failed"
    STOPPED = "stopped"


TERMINAL_STATUSES = frozenset(
    (AgentStatus.FINISHED, AgentStatus.FAILED, AgentStatus.STOPPED)
)


class AgentState(BaseModel):
    """Current progress and previous-step context for one selected HWND."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    task: str = Field(min_length=1)
    hwnd: int = Field(gt=0)
    status: AgentStatus = AgentStatus.IDLE
    step: int = Field(default=0, ge=0)
    max_steps: int = Field(default=30, gt=0)
    last_action: AgentAction | None = None
    last_result: ActionResult | None = None
    message: str = ""
