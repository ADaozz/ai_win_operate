from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from PIL import Image
from pydantic import HttpUrl, SecretStr

from app.actions.schema import (
    ActionResult,
    AgentDecision,
    ClickAction,
    FailAction,
    FinishAction,
    decision_json_schema,
)
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
from app.common.logging import configure_logging
from app.config.settings import Settings
from app.llm.openai_compatible import (
    OpenAICompatibleVisionClient,
    build_httpx_client,
    is_loopback_base_url,
)
from app.llm.qwen_client import QwenClient
from app.vision.frame_diff import FrameDiffResult
from app.windows.models import WindowInfo

TEST_KEY = "unit-test-secret-never-log"


def make_settings(
    key: str | None = TEST_KEY,
    response_format: str = "json_schema",
    auth_mode: str = "bearer",
) -> Settings:
    return Settings.model_construct(
        llm_provider="openai_compatible",
        llm_model="qwen-test-vision",
        llm_base_url=HttpUrl("https://llm.example.test/compatible-mode/v1"),
        llm_timeout=2.5,
        llm_response_format=response_format,
        llm_auth_mode=auth_mode,
        llm_api_key=SecretStr(key) if key is not None else None,
        agent_max_plan_actions=5,
    )


def make_observation() -> Observation:
    return Observation(
        task="点击文件菜单",
        step=3,
        window=WindowInfo(
            hwnd=123,
            title="Notepad",
            pid=456,
            left=10,
            top=20,
            width=800,
            height=600,
        ),
        previous_action=ClickAction(type="click", x=0.4, y=0.3),
        previous_result=ActionResult(
            success=True,
            message="clicked",
            duration_ms=12,
            frame_diff_score=0.0,
            ui_changed=False,
        ),
        frame_diff=FrameDiffResult(changed=False, score=0.0, threshold=0.02),
    )


def make_screenshot() -> Image.Image:
    return Image.new("RGB", (16, 12), (20, 40, 60))


def model_response(payload: dict[str, Any]) -> httpx.Response:
    if "actions" not in payload:
        summary = payload.get("decision_summary", "单元测试决策说明。")
        action = {k: v for k, v in payload.items() if k != "decision_summary"}
        payload = {
            "decision_summary": summary,
            "actions": [{"decision_summary": "", **action}],
        }
    elif "decision_summary" not in payload:
        payload = {"decision_summary": "单元测试决策说明。", **payload}
    return httpx.Response(
        200,
        json={"choices": [{"message": {"content": json.dumps(payload)}}]},
        headers={"x-request-id": "request-123"},
    )


def run_decide(
    handler: httpx.MockTransport,
    *,
    settings: Settings | None = None,
    observation: Observation | None = None,
) -> AgentDecision:
    async def run() -> AgentDecision:
        async with httpx.AsyncClient(transport=handler) as http_client:
            client = QwenClient(settings or make_settings(), http_client)
            return await client.decide(
                observation or make_observation(),
                make_screenshot(),
            )

    return asyncio.run(run())


def test_request_uses_configured_endpoint_model_image_and_schema() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return model_response(
            {
                "decision_summary": "当前信息不足，先打开目标菜单。",
                "actions": [
                    {
                        "type": "click",
                        "x": 0.05,
                        "y": 0.04,
                    }
                ],
            }
        )

    decision = run_decide(httpx.MockTransport(handler))

    assert isinstance(decision, AgentDecision)
    assert decision.decision_summary == "当前信息不足，先打开目标菜单。"
    assert isinstance(decision.actions[0], ClickAction)
    assert len(requests) == 1
    request = requests[0]
    assert str(request.url) == (
        "https://llm.example.test/compatible-mode/v1/chat/completions"
    )
    assert request.headers["authorization"] == f"Bearer {TEST_KEY}"
    payload = json.loads(request.content)
    assert payload["model"] == "qwen-test-vision"
    image_url = payload["messages"][1]["content"][1]["image_url"]["url"]
    assert image_url.startswith("data:image/jpeg;base64,")
    assert base64.b64decode(image_url.split(",", 1)[1]).startswith(b"\xff\xd8")
    schema = payload["response_format"]["json_schema"]["schema"]
    assert payload["response_format"]["type"] == "json_schema"
    assert payload["response_format"]["json_schema"]["strict"] is True
    assert payload["response_format"]["json_schema"]["name"] == "agent_decision"
    assert "actions" in schema["properties"]
    assert "decision_summary" in schema["properties"]
    system_prompt = payload["messages"][0]["content"]
    assert "Allowed hotkeys" in system_prompt
    assert "ENTER" in system_prompt
    assert "not RETURN" in system_prompt
    assert '["CTRL", "A"], never ["CTRL+A"]' in system_prompt
    assert "重复动作已被跳过" in system_prompt
    assert "不得重复被拦截的动作" in system_prompt
    assert "当前可见上下文对本任务是否足够" in system_prompt
    assert "decision_summary" in system_prompt
    assert "多个可滚动区域" in system_prompt
    assert "frame_diff" in system_prompt
    assert "多步计划" in system_prompt

    prompt = payload["messages"][1]["content"][0]["text"]
    assert "点击文件菜单" in prompt
    assert "当前步骤：\n\n3" in prompt
    assert '"hwnd": 123' in prompt
    assert "UI 元素：\n\n[]" in prompt
    assert '"type": "click"' in prompt
    assert '"success": true' in prompt
    assert "上一轮 frame_diff：" in prompt
    assert "多步计划" in prompt or "多步计划" in system_prompt
    assert image_url not in prompt


def test_repeated_action_feedback_adds_mandatory_recovery_constraint() -> None:
    requests: list[httpx.Request] = []
    observation = make_observation().model_copy(
        update={
            "previous_result": ActionResult(
                success=False,
                message="重复动作已跳过且未执行；禁止返回相同动作",
            ),
            "frame_diff": None,
        }
    )

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return model_response({"type": "fail", "reason": "no alternative"})

    run_decide(httpx.MockTransport(handler), observation=observation)

    payload = json.loads(requests[0].content)
    prompt = payload["messages"][1]["content"][0]["text"]
    assert "上一个动作已被禁止" in prompt
    assert "并未执行" in prompt
    assert "禁止再次返回相同的动作 JSON" in prompt


def test_qwen_json_object_compatibility_still_sends_decision_schema() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return model_response({"type": "finish", "result": "done"})

    decision = run_decide(
        httpx.MockTransport(handler),
        settings=make_settings(response_format="json_object"),
    )

    assert isinstance(decision.actions[0], FinishAction)
    payload = json.loads(requests[0].content)
    assert payload["response_format"] == {"type": "json_object"}
    assert payload["enable_thinking"] is False
    schema_text = json.dumps(decision_json_schema(), ensure_ascii=False, sort_keys=True)
    assert schema_text in payload["messages"][0]["content"]


def test_local_json_object_omits_enable_thinking() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return model_response({"type": "finish", "result": "done"})

    settings = make_settings(response_format="json_object")
    settings = settings.model_copy(
        update={"llm_base_url": HttpUrl("http://localhost:8000/v1")}
    )

    async def run() -> AgentDecision:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
            client = QwenClient(settings, http_client)
            return await client.decide(make_observation(), make_screenshot())

    decision = asyncio.run(run())
    assert isinstance(decision.actions[0], FinishAction)
    payload = json.loads(requests[0].content)
    assert "enable_thinking" not in payload


@pytest.mark.parametrize(
    ("payload", "expected_type"),
    [
        ({"type": "finish", "result": "done"}, FinishAction),
        ({"type": "fail", "reason": "blocked"}, FailAction),
    ],
)
def test_terminal_actions_are_validated(
    payload: dict[str, Any], expected_type: type
) -> None:
    decision = run_decide(httpx.MockTransport(lambda _: model_response(payload)))
    assert isinstance(decision.actions[0], expected_type)


@pytest.mark.parametrize(
    "payload",
    [
        {"type": "shell", "command": "whoami"},
        {"type": "click", "x": 1.01, "y": 0.5},
        {"decision_summary": "bad", "actions": [{"type": "shell", "command": "x"}]},
    ],
)
def test_invalid_structured_actions_are_rejected(payload: dict[str, Any]) -> None:
    with pytest.raises(StructuredOutputError):
        run_decide(httpx.MockTransport(lambda _: model_response(payload)))


def test_empty_model_content_is_rejected() -> None:
    response = httpx.Response(
        200,
        json={"choices": [{"message": {"content": "  "}}]},
    )
    with pytest.raises(EmptyModelResponseError):
        run_decide(httpx.MockTransport(lambda _: response))


def test_missing_public_decision_summary_is_rejected() -> None:
    response = httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "decision_summary": "   ",
                                "actions": [{"type": "click", "x": 0.2, "y": 0.3}],
                            }
                        )
                    }
                }
            ]
        },
    )

    with pytest.raises(StructuredOutputError):
        run_decide(httpx.MockTransport(lambda _: response))


def test_invalid_response_envelope_is_rejected() -> None:
    with pytest.raises(LLMResponseStructureError):
        run_decide(
            httpx.MockTransport(lambda _: httpx.Response(200, json={"choices": []}))
        )


def test_http_error_is_safe_and_typed() -> None:
    with pytest.raises(LLMHTTPError) as error:
        run_decide(
            httpx.MockTransport(
                lambda _: httpx.Response(429, text="provider response must stay private")
            )
        )
    assert error.value.status_code == 429
    assert "provider response" not in str(error.value)


def test_timeout_is_converted_to_typed_error() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("private timeout details", request=request)

    with pytest.raises(LLMTimeoutError, match="timed out"):
        run_decide(httpx.MockTransport(timeout))


def test_missing_api_key_fails_before_transport() -> None:
    called = False

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return model_response({"type": "finish", "result": "unexpected"})

    with pytest.raises(MissingApiKeyError, match="WGA_LLM_API_KEY"):
        run_decide(httpx.MockTransport(handler), settings=make_settings(None))
    assert called is False


def test_logs_never_contain_key_image_or_response_body(tmp_path: Path) -> None:
    configure_logging("INFO", tmp_path)
    private_body = "private-provider-body-never-log"

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text=private_body, headers={"x-request-id": "safe-id"})

    with pytest.raises(LLMHTTPError):
        run_decide(httpx.MockTransport(handler))

    logs = (tmp_path / "app.log").read_text(encoding="utf-8")
    assert TEST_KEY not in logs
    assert private_body not in logs
    assert "Authorization" not in logs
    assert "data:image" not in logs
    assert "base64" not in logs
    assert '"model": "qwen-test-vision"' in logs
    assert '"status_code": 500' in logs
    assert '"request_id": "safe-id"' in logs


def test_openai_compatible_auth_none_omits_authorization_header() -> None:
    client = OpenAICompatibleVisionClient(
        model="test",
        base_url="http://gateway.test/v1",
        timeout=5,
        response_format="json_object",
        max_plan_actions=3,
        allowed_hotkeys=("ENTER",),
        auth_mode="none",
        api_key=None,
    )
    headers = client._request_headers()
    assert "Authorization" not in headers


def test_openai_compatible_bearer_requires_key() -> None:
    client = OpenAICompatibleVisionClient(
        model="test",
        base_url="http://gateway.test/v1",
        timeout=5,
        response_format="json_object",
        max_plan_actions=3,
        allowed_hotkeys=("ENTER",),
        auth_mode="bearer",
        api_key=None,
    )
    with pytest.raises(MissingApiKeyError, match="WGA_LLM_API_KEY"):
        client._request_headers()


@pytest.mark.parametrize(
    ("base_url", "expected"),
    [
        ("http://localhost:8000/v1", True),
        ("http://127.0.0.1:8000/v1", True),
        ("http://[::1]:8000/v1", True),
        ("https://llm.example.test/compatible-mode/v1", False),
    ],
)
def test_is_loopback_base_url(base_url: str, expected: bool) -> None:
    assert is_loopback_base_url(base_url) is expected


def test_local_gateway_http_client_disables_env_proxy() -> None:
    client = build_httpx_client(base_url="http://localhost:8000/v1", timeout=2.5)
    try:
        assert client._trust_env is False
    finally:
        asyncio.run(client.aclose())


def test_remote_gateway_http_client_keeps_env_proxy() -> None:
    client = build_httpx_client(
        base_url="https://llm.example.test/compatible-mode/v1",
        timeout=2.5,
    )
    try:
        assert client._trust_env is True
    finally:
        asyncio.run(client.aclose())


def test_transport_error_includes_safe_cause(tmp_path: Path) -> None:
    configure_logging("INFO", tmp_path)

    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadError("proxy read failed", request=request)

    with pytest.raises(LLMTransportError, match="proxy read failed"):
        run_decide(httpx.MockTransport(fail))

    logs = (tmp_path / "app.log").read_text(encoding="utf-8")
    assert '"event": "llm_transport_error"' in logs
    assert '"error_type": "ReadError"' in logs
    assert "proxy read failed" in logs
