"""Ask Qwen for one validated AgentDecision without executing it."""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from pathlib import Path

from PIL import Image

from app.agent.observation import Observation
from app.common.exceptions import LLMClientError
from app.config.settings import load_settings
from app.llm.qwen_client import QwenClient
from app.windows.models import WindowInfo


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("screenshot", type=Path, help="local screenshot image")
    parser.add_argument("--task", required=True, help="GUI task for model-only decision")
    return parser


async def decide_only(screenshot_path: Path, task: str) -> str:
    """Return validated decision JSON; never instantiate a GUI executor."""
    with Image.open(screenshot_path) as source:
        screenshot = source.convert("RGB")
    observation = Observation(
        task=task,
        step=0,
        window=WindowInfo(
            hwnd=1,
            title=f"Debug screenshot: {screenshot_path.name}",
            pid=0,
            left=0,
            top=0,
            width=screenshot.width,
            height=screenshot.height,
        ),
    )
    async with QwenClient(load_settings()) as client:
        decision = await client.decide(observation, screenshot)
    return decision.model_dump_json()


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        output = asyncio.run(decide_only(args.screenshot, args.task))
    except (OSError, LLMClientError, ValueError) as exc:
        print(f"Model-only decision failed: {exc}", file=sys.stderr)
        return 1
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
