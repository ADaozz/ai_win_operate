"""Backward-compatible alias for the OpenAI-compatible vision client."""

from __future__ import annotations

import httpx

from app.config.settings import Settings
from app.llm.openai_compatible import OpenAICompatibleVisionClient


class QwenClient:
    """Preserve the historical ``QwenClient(settings, client)`` construction API."""

    def __init__(
        self,
        settings: Settings,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._inner = OpenAICompatibleVisionClient.from_settings(settings, client=client)

    def __getattr__(self, name: str) -> object:
        return getattr(self._inner, name)

    async def aclose(self) -> None:
        await self._inner.aclose()


OpenAICompatibleVisionClientAlias = OpenAICompatibleVisionClient

__all__ = ["QwenClient", "OpenAICompatibleVisionClient"]
