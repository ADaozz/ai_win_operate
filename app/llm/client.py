"""Provider-neutral vision agent decision interface."""

from __future__ import annotations

from typing import Protocol

from PIL import Image

from app.actions.schema import AgentDecision
from app.agent.observation import Observation


class VisionAgentClient(Protocol):
    async def decide(
        self,
        observation: Observation,
        screenshot: Image.Image,
    ) -> AgentDecision: ...
