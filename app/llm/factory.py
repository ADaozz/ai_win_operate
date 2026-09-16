"""Construct VisionAgentClient implementations from settings."""

from __future__ import annotations

import httpx

from app.config.settings import Settings
from app.llm.client import VisionAgentClient
from app.llm.openai_compatible import OpenAICompatibleVisionClient


def create_vision_client(
    settings: Settings,
    client: httpx.AsyncClient | None = None,
) -> VisionAgentClient:
    """Return the configured vision client for AgentRuntime."""
    provider = settings.llm_provider
    if provider == "openai_compatible":
        return OpenAICompatibleVisionClient.from_settings(settings, client=client)
    raise ValueError(f"Unsupported llm_provider: {provider}")
