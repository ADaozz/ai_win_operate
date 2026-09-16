"""Serializable metadata sent to a vision agent separately from screenshots."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.actions.schema import ActionResult, AgentAction
from app.vision.frame_diff import FrameDiffResult
from app.windows.models import WindowInfo


class Observation(BaseModel):
    """One model observation; image bytes are deliberately not part of this model."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    task: str = Field(min_length=1)
    step: int = Field(ge=0)
    window: WindowInfo
    ui_elements: list[dict[str, Any]] = Field(default_factory=list)
    previous_action: AgentAction | None = None
    previous_result: ActionResult | None = None
    frame_diff: FrameDiffResult | None = None
