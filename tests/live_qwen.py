"""Explicit real-service Qwen connectivity test.

This filename intentionally does not match pytest's normal discovery pattern.
Run it directly only when a real API request is desired.
"""

from __future__ import annotations

import asyncio

from PIL import Image, ImageDraw

from app.actions.schema import FinishAction
from app.agent.observation import Observation
from app.config.settings import load_settings
from app.llm.qwen_client import QwenClient
from app.windows.models import WindowInfo


def test_qwen_real_connection_returns_validated_finish_action() -> None:
    """Call Qwen once, validate AgentDecision, and never execute the result."""
    screenshot = Image.new("RGB", (640, 360), "white")
    draw = ImageDraw.Draw(screenshot)
    draw.text((32, 32), "Qwen vision connectivity test", fill="black")
    observation = Observation(
        task=(
            "这是一次只读连通性测试。不要提出或执行 GUI 操作；"
            "请返回只含 finish 的 actions 计划，result 说明连接成功。"
        ),
        step=0,
        window=WindowInfo(
            hwnd=1,
            title="Qwen 只读连通性测试",
            pid=0,
            left=0,
            top=0,
            width=screenshot.width,
            height=screenshot.height,
        ),
    )

    async def decide_once() -> FinishAction:
        async with QwenClient(load_settings()) as client:
            decision = await client.decide(observation, screenshot)
        assert len(decision.actions) == 1, decision.model_dump_json()
        action = decision.actions[0]
        assert isinstance(action, FinishAction), decision.model_dump_json()
        return action

    action = asyncio.run(decide_once())
    print(f"validated_action={action.model_dump_json()}")
