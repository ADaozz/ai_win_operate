"""OpenAI-compatible multimodal vision client for AgentDecision planning."""

from __future__ import annotations

import base64
import json
import time
from io import BytesIO
from types import TracebackType
from typing import Any, Literal, Self
from urllib.parse import urlparse

import httpx
from PIL import Image
from pydantic import SecretStr, ValidationError

from app.actions.schema import AgentDecision, decision_json_schema, parse_decision
from app.actions.validator import DEFAULT_ALLOWED_HOTKEYS
from app.agent.observation import Observation
from app.common.exceptions import (
    EmptyModelResponseError,
    LLMHTTPError,
    LLMResponseStructureError,
    LLMTimeoutError,
    LLMTransportError,
    MissingApiKeyError,
    StructuredOutputError,
)
from app.common.logging import get_logger
from app.config.settings import Settings
from app.llm.prompts import SYSTEM_PROMPT, build_user_prompt

logger = get_logger(__name__)

_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def is_loopback_base_url(base_url: str) -> bool:
    """Return True when the LLM gateway host is a local loopback address."""
    host = (urlparse(base_url).hostname or "").strip().lower()
    return host in _LOOPBACK_HOSTS


def build_httpx_client(*, base_url: str, timeout: float) -> httpx.AsyncClient:
    """Build an HTTP client that bypasses OS/env proxies for local gateways.

    Windows system proxy settings are otherwise applied by httpx (trust_env=True)
    and often break ``http://localhost`` / ``127.0.0.1`` LLM gateways with
    ``ReadError`` / ``ConnectError`` before any HTTP status is returned.
    """
    return httpx.AsyncClient(
        timeout=timeout,
        trust_env=not is_loopback_base_url(base_url),
    )


class OpenAICompatibleVisionClient:
    """Call any OpenAI-compatible /chat/completions endpoint with vision input."""

    def __init__(
        self,
        *,
        model: str,
        base_url: str,
        timeout: float,
        response_format: Literal["json_schema", "json_object"],
        max_plan_actions: int,
        allowed_hotkeys: tuple[str, ...],
        auth_mode: Literal["none", "bearer"] = "bearer",
        api_key: SecretStr | None = None,
        max_image_width: int = 1600,
        jpeg_quality: int = 85,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._model = model
        self._endpoint = f"{base_url.rstrip('/')}/chat/completions"
        self._timeout = timeout
        self._response_format = response_format
        self._max_plan_actions = max_plan_actions
        self._allowed_hotkeys = allowed_hotkeys
        self._auth_mode = auth_mode
        self._api_key = api_key
        self._max_image_width = max_image_width
        self._jpeg_quality = jpeg_quality
        self._client = client or build_httpx_client(
            base_url=base_url,
            timeout=self._timeout,
        )
        self._owns_client = client is None

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        client: httpx.AsyncClient | None = None,
    ) -> OpenAICompatibleVisionClient:
        return cls(
            model=settings.llm_model,
            base_url=str(settings.llm_base_url),
            timeout=settings.llm_timeout,
            response_format=settings.llm_response_format,
            max_plan_actions=settings.agent_max_plan_actions,
            allowed_hotkeys=tuple(settings.allowed_hotkeys),
            auth_mode=settings.llm_auth_mode,
            api_key=settings.resolved_llm_api_key,
            max_image_width=settings.llm_max_image_width,
            jpeg_quality=settings.llm_jpeg_quality,
            client=client,
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def decide(
        self,
        observation: Observation,
        screenshot: Image.Image,
    ) -> AgentDecision:
        started = time.perf_counter()
        headers = self._request_headers()
        payload = self._request_payload(observation, screenshot)
        try:
            response = await self._client.post(
                self._endpoint,
                json=payload,
                headers=headers,
                timeout=self._timeout,
            )
        except httpx.TimeoutException as exc:
            logger.error(
                "llm_request_timeout",
                model=self._model,
                duration_ms=self._duration_ms(started),
            )
            raise LLMTimeoutError("LLM request timed out") from exc
        except httpx.RequestError as exc:
            cause = str(exc).strip() or type(exc).__name__
            logger.error(
                "llm_transport_error",
                model=self._model,
                duration_ms=self._duration_ms(started),
                error_type=type(exc).__name__,
                error=cause[:300],
            )
            raise LLMTransportError(
                f"LLM request failed before receiving a response: {cause[:200]}"
            ) from exc

        request_id = self._request_id(response)
        metadata = {
            "model": self._model,
            "status_code": response.status_code,
            "duration_ms": self._duration_ms(started),
            "request_id": request_id,
        }
        if not response.is_success:
            logger.error("llm_http_error", **metadata)
            raise LLMHTTPError(response.status_code)

        try:
            content = self._response_content(response)
        except EmptyModelResponseError:
            logger.error("llm_empty_response", **metadata)
            raise
        except LLMResponseStructureError:
            logger.error("llm_response_structure_error", **metadata)
            raise

        try:
            decision = parse_decision(content, max_actions=self._max_plan_actions)
        except (ValidationError, ValueError, TypeError) as exc:
            logger.error("llm_structured_output_invalid", **metadata)
            raise StructuredOutputError(
                "LLM structured output is not a valid AgentDecision"
            ) from exc
        if not decision.decision_summary:
            logger.error("llm_decision_summary_missing", **metadata)
            raise StructuredOutputError(
                "LLM AgentDecision is missing a public decision_summary"
            )

        logger.info(
            "llm_request_completed",
            action_count=len(decision.actions),
            action_type=decision.actions[0].type,
            **metadata,
        )
        return decision

    def _request_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._auth_mode == "none":
            return headers
        if self._api_key is None:
            raise MissingApiKeyError("WGA_LLM_API_KEY is not configured")
        value = self._api_key.get_secret_value()
        if not value:
            raise MissingApiKeyError("WGA_LLM_API_KEY is not configured")
        headers["Authorization"] = f"Bearer {value}"
        return headers

    def _request_payload(
        self,
        observation: Observation,
        screenshot: Image.Image,
    ) -> dict[str, Any]:
        schema = decision_json_schema()
        schema_instruction = (
            "\nReturn exactly one JSON object that validates against this JSON Schema. "
            "The object must include decision_summary and a non-empty actions array "
            f"(at most {self._max_plan_actions} actions). "
            "Do not add Markdown or explanatory text.\nJSON Schema:\n"
            f"{json.dumps(schema, ensure_ascii=False, sort_keys=True)}"
            "\nAllowed hotkeys:\n"
            f"{json.dumps(list(self._allowed_hotkeys), ensure_ascii=False)}"
            "\nHotkey keys must be separate array items: use "
            '["CTRL", "A"], never ["CTRL+A"].'
            " For the Enter key, use the canonical key name ENTER, not RETURN."
        )
        if self._response_format == "json_schema":
            response_format: dict[str, Any] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "agent_decision",
                    "strict": True,
                    "schema": schema,
                },
            }
        else:
            response_format = {"type": "json_object"}

        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT + schema_instruction},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": build_user_prompt(observation)},
                        {
                            "type": "image_url",
                            "image_url": {"url": self._image_data_url(screenshot)},
                        },
                    ],
                },
            ],
            "response_format": response_format,
        }
        # DashScope accepts this Qwen-specific flag; strict OpenAI-compatible
        # local gateways reject unknown top-level parameters.
        if self._response_format == "json_object" and not is_loopback_base_url(
            self._endpoint
        ):
            payload["enable_thinking"] = False
        return payload

    def _image_data_url(self, screenshot: Image.Image) -> str:
        image = screenshot.convert("RGB")
        if image.width > self._max_image_width:
            image.thumbnail(
                (self._max_image_width, image.height),
                Image.Resampling.LANCZOS,
            )
        buffer = BytesIO()
        image.save(buffer, format="JPEG", quality=self._jpeg_quality)
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        return f"data:image/jpeg;base64,{encoded}"

    @staticmethod
    def _response_content(response: httpx.Response) -> str | bytes | dict[str, Any]:
        if not response.content:
            raise EmptyModelResponseError("LLM returned an empty response")
        try:
            payload = response.json()
        except ValueError as exc:
            raise LLMResponseStructureError(
                "LLM response has an invalid structure"
            ) from exc
        if not isinstance(payload, dict):
            raise LLMResponseStructureError("LLM response has an invalid structure")
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise LLMResponseStructureError("LLM response has an invalid structure")
        choice = choices[0]
        if not isinstance(choice, dict):
            raise LLMResponseStructureError("LLM response has an invalid structure")
        message = choice.get("message")
        if not isinstance(message, dict) or "content" not in message:
            raise LLMResponseStructureError("LLM response has an invalid structure")
        content = message["content"]
        if content is None or (isinstance(content, str) and not content.strip()):
            raise EmptyModelResponseError("LLM returned an empty model response")
        if not isinstance(content, (str, bytes, dict)):
            raise LLMResponseStructureError("LLM response has an invalid structure")
        return content

    @staticmethod
    def _request_id(response: httpx.Response) -> str | None:
        value = response.headers.get("x-request-id") or response.headers.get(
            "request-id"
        )
        return value[:128] if value else None

    @staticmethod
    def _duration_ms(started: float) -> int:
        return max(0, round((time.perf_counter() - started) * 1000))
