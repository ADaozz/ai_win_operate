from __future__ import annotations

import asyncio

from PIL import Image

from app.actions.executor import ActionExecutor
from app.actions.schema import AgentAction, AgentDecision, parse_action, parse_decision
from app.actions.validator import ActionValidator
from app.agent.observation import Observation
from app.agent.runtime import AgentRuntime, RuntimeEvent, RuntimePhase
from app.agent.state import AgentState, AgentStatus
from app.windows.models import WindowInfo


class StableWindowManager:
    def __init__(self) -> None:
        self.window = WindowInfo(
            hwnd=41,
            title="Runtime Target",
            pid=42,
            left=10,
            top=20,
            width=800,
            height=600,
        )

    def exists(self, hwnd: int) -> bool:
        return hwnd == self.window.hwnd

    def get_window(self, hwnd: int) -> WindowInfo:
        assert hwnd == self.window.hwnd
        return self.window

    def is_minimized(self, hwnd: int) -> bool:
        assert hwnd == self.window.hwnd
        return False


class RecordingCapture:
    def __init__(self, *, mutate: bool = False) -> None:
        self.calls: list[int] = []
        self._mutate = mutate
        self._index = 0

    def capture(self, hwnd: int) -> Image.Image:
        self.calls.append(hwnd)
        self._index += 1
        if self._mutate:
            # Alternate shades so consecutive frames differ above threshold.
            shade = 255 if self._index % 2 else 0
            return Image.new("RGB", (320, 200), (shade, shade, shade))
        return Image.new("RGB", (320, 200), "white")


class RecordingInputExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def click(self, hwnd: int, x: float, y: float, **kwargs: object) -> None:
        self.calls.append(("click", hwnd, x, y, kwargs))

    def double_click(self, hwnd: int, x: float, y: float) -> None:
        self.calls.append(("double_click", hwnd, x, y))

    def right_click(self, hwnd: int, x: float, y: float) -> None:
        self.calls.append(("right_click", hwnd, x, y))

    def type_text(self, hwnd: int, text: str) -> None:
        self.calls.append(("type", hwnd, text))

    def hotkey(self, hwnd: int, keys: list[str]) -> None:
        self.calls.append(("hotkey", hwnd, keys))

    def scroll(self, hwnd: int, direction: str, amount: int = 3) -> None:
        self.calls.append(("scroll", hwnd, direction, amount))


class SequenceClient:
    def __init__(self, decisions: list[AgentDecision]) -> None:
        self.decisions = decisions
        self.observations: list[Observation] = []

    async def decide(
        self,
        observation: Observation,
        screenshot: Image.Image,
    ) -> AgentDecision:
        assert screenshot.size == (320, 200)
        self.observations.append(observation)
        return self.decisions.pop(0)


class BlockingClient:
    def __init__(self, decisions: list[AgentDecision]) -> None:
        self.decisions = decisions
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def decide(
        self,
        observation: Observation,
        screenshot: Image.Image,
    ) -> AgentDecision:
        del observation, screenshot
        self.started.set()
        await self.release.wait()
        return self.decisions.pop(0)


def decision_from_actions(
    *actions: AgentAction | dict[str, object],
    summary: str = "测试计划",
) -> AgentDecision:
    parsed: list[AgentAction] = []
    for item in actions:
        if isinstance(item, dict):
            parsed.append(parse_action(item))
        else:
            parsed.append(item)
    return AgentDecision(decision_summary=summary, actions=parsed)


def make_runtime(
    client: object,
    *,
    max_steps: int = 30,
    max_repeated_actions: int = 3,
    max_repeated_clicks: int = 5,
    repeat_recovery_attempts: int = 3,
    click_repeat_recovery_attempts: int = 8,
    mutate_frames: bool = False,
) -> tuple[AgentRuntime, RecordingCapture, RecordingInputExecutor, list[RuntimeEvent]]:
    manager = StableWindowManager()
    capture = RecordingCapture(mutate=mutate_frames)
    inputs = RecordingInputExecutor()
    events: list[RuntimeEvent] = []
    runtime = AgentRuntime(
        AgentState(task="完成测试任务", hwnd=41, max_steps=max_steps),
        manager,
        capture,
        client,  # type: ignore[arg-type]
        ActionValidator(manager),
        ActionExecutor(inputs, sleep=lambda _seconds: None),
        action_delay_ms=0,
        max_repeated_actions=max_repeated_actions,
        max_repeated_clicks=max_repeated_clicks,
        repeat_recovery_attempts=repeat_recovery_attempts,
        click_repeat_recovery_attempts=click_repeat_recovery_attempts,
        on_event=events.append,
    )
    return runtime, capture, inputs, events


def test_runtime_executes_validated_action_then_finishes() -> None:
    client = SequenceClient(
        [
            decision_from_actions(
                {
                    "type": "click",
                    "x": 0.25,
                    "y": 0.5,
                    "decision_summary": "菜单尚未展开，先点击菜单入口。",
                },
                summary="菜单尚未展开，先点击菜单入口。",
            ),
            decision_from_actions(
                {"type": "finish", "result": "完成"},
                summary="任务已完成。",
            ),
        ]
    )
    runtime, capture, inputs, events = make_runtime(client)

    state = asyncio.run(runtime.run())

    assert state.status is AgentStatus.FINISHED
    assert state.step == 2
    assert state.message == "完成"
    # observe + verify after click + observe for finish
    assert capture.calls == [41, 41, 41]
    assert inputs.calls == [("click", 41, 0.25, 0.5, {"button": "left"})]
    assert client.observations[1].previous_action is not None
    assert client.observations[1].previous_action.type == "click"
    assert client.observations[1].previous_result is not None
    assert client.observations[1].previous_result.success is True
    assert client.observations[1].previous_result.ui_changed is False
    assert client.observations[1].frame_diff is not None
    assert client.observations[1].frame_diff.changed is False
    assert any(event.phase is RuntimePhase.VALIDATE for event in events)
    assert any(event.phase is RuntimePhase.VERIFY for event in events)
    decision = next(
        event
        for event in events
        if event.phase is RuntimePhase.DECIDE and "计划" in event.message
    )
    assert decision.step == 1
    assert decision.decision_summary == "菜单尚未展开，先点击菜单入口。"
    execution = next(
        event
        for event in events
        if event.phase is RuntimePhase.EXECUTE and event.success is True
    )
    assert execution.step == 1
    assert "Frame Diff" in execution.message


def test_runtime_honors_model_fail_without_gui_input() -> None:
    client = SequenceClient(
        [
            decision_from_actions(
                {"type": "fail", "reason": "无法安全完成"},
                summary="无法安全完成。",
            )
        ]
    )
    runtime, _capture, inputs, _events = make_runtime(client)

    state = asyncio.run(runtime.run())

    assert state.status is AgentStatus.FAILED
    assert state.step == 1
    assert state.message == "无法安全完成"
    assert inputs.calls == []


def test_runtime_records_model_action_rejected_by_validator() -> None:
    client = SequenceClient(
        [
            decision_from_actions(
                {"type": "hotkey", "keys": ["ALT", "F4"]},
                summary="错误组合键。",
            )
        ]
    )
    runtime, _capture, inputs, events = make_runtime(client)

    state = asyncio.run(runtime.run())

    assert state.status is AgentStatus.FAILED
    assert state.step == 1
    assert state.last_action is not None
    assert state.last_action.type == "hotkey"
    assert state.last_result is not None
    assert state.last_result.success is False
    assert "Forbidden hotkey" in state.message
    assert inputs.calls == []
    assert any(event.phase is RuntimePhase.BLOCKED for event in events)


def test_runtime_stops_at_max_steps() -> None:
    client = SequenceClient(
        [
            decision_from_actions(
                {"type": "wait", "milliseconds": 100},
                summary="等待。",
            )
        ]
    )
    runtime, _capture, inputs, _events = make_runtime(client, max_steps=1)

    state = asyncio.run(runtime.run())

    assert state.status is AgentStatus.FAILED
    assert state.step == 1
    assert state.message == "已达到最大步骤数"
    assert inputs.calls == []


def test_repeated_click_is_skipped_and_model_can_recover() -> None:
    client = SequenceClient(
        [
            *[
                decision_from_actions(
                    {"type": "click", "x": 0.5, "y": 0.5},
                    summary="重复点击。",
                )
                for _ in range(3)
            ],
            decision_from_actions(
                {"type": "finish", "result": "已换策略完成"},
                summary="完成。",
            ),
        ]
    )
    runtime, _capture, inputs, events = make_runtime(
        client,
        max_repeated_clicks=3,
    )

    state = asyncio.run(runtime.run())

    assert state.status is AgentStatus.FINISHED
    assert state.step == 4
    assert state.message == "已换策略完成"
    assert len(inputs.calls) == 2
    assert client.observations[3].previous_result is not None
    assert client.observations[3].previous_result.success is False
    assert "重复动作已跳过" in client.observations[3].previous_result.message
    assert any(event.phase is RuntimePhase.BLOCKED for event in events)


def test_repeated_click_fails_only_after_recovery_attempts_are_exhausted() -> None:
    repeated = [
        decision_from_actions(
            {"type": "click", "x": 0.5, "y": 0.5},
            summary="重复。",
        )
        for _ in range(5)
    ]
    runtime, _capture, inputs, events = make_runtime(
        SequenceClient(repeated),
        max_repeated_clicks=3,
        click_repeat_recovery_attempts=3,
    )

    state = asyncio.run(runtime.run())

    assert state.status is AgentStatus.FAILED
    assert state.step == 5
    assert "3 次恢复" in state.message
    assert len(inputs.calls) == 2
    assert len([event for event in events if event.phase is RuntimePhase.BLOCKED]) == 3


def test_stop_cancels_inflight_decision_and_prevents_execution() -> None:
    async def scenario() -> tuple[AgentStatus, list[tuple[object, ...]]]:
        client = BlockingClient(
            [
                decision_from_actions(
                    {"type": "click", "x": 0.5, "y": 0.5},
                    summary="点击。",
                )
            ]
        )
        runtime, _capture, inputs, _events = make_runtime(client)
        task = asyncio.create_task(runtime.run())
        await client.started.wait()
        assert runtime.stop() is True
        state = await task
        return state.status, inputs.calls

    status, calls = asyncio.run(scenario())

    assert status is AgentStatus.STOPPED
    assert calls == []


def test_pause_holds_model_action_until_resume() -> None:
    async def scenario() -> tuple[AgentStatus, list[tuple[object, ...]]]:
        client = BlockingClient(
            [
                decision_from_actions(
                    {"type": "click", "x": 0.2, "y": 0.3},
                    summary="点击。",
                ),
                decision_from_actions(
                    {"type": "finish", "result": "完成"},
                    summary="完成。",
                ),
            ]
        )
        runtime, _capture, inputs, _events = make_runtime(client)
        task = asyncio.create_task(runtime.run())
        await client.started.wait()
        assert runtime.pause() is True
        client.release.set()
        await asyncio.sleep(0.1)
        assert inputs.calls == []
        assert runtime.resume() is True
        state = await task
        return state.status, inputs.calls

    status, calls = asyncio.run(scenario())

    assert status is AgentStatus.FINISHED
    assert len(calls) == 1


def test_multi_step_plan_executes_without_second_model_call() -> None:
    client = SequenceClient(
        [
            decision_from_actions(
                {"type": "click", "x": 0.1, "y": 0.2},
                {"type": "type", "text": "hello"},
                {"type": "finish", "result": "已输入"},
                summary="点击输入框并输入后完成。",
            )
        ]
    )
    runtime, capture, inputs, events = make_runtime(client, mutate_frames=True)

    state = asyncio.run(runtime.run())

    assert state.status is AgentStatus.FINISHED
    assert state.step == 3
    assert state.message == "已输入"
    assert len(client.decisions) == 0
    assert len(client.observations) == 1
    assert inputs.calls == [
        ("click", 41, 0.1, 0.2, {"button": "left"}),
        ("type", 41, "hello"),
    ]
    assert len([event for event in events if event.phase is RuntimePhase.VERIFY]) == 4
    # observe + verify click + verify type (finish skips verify)
    assert len(capture.calls) == 3


def test_multi_step_plan_continues_when_click_frame_diff_is_low() -> None:
    client = SequenceClient(
        [
            decision_from_actions(
                {"type": "click", "x": 0.4, "y": 0.5},
                {"type": "type", "text": "2684"},
                {"type": "finish", "result": "表单步骤已执行"},
                summary="聚焦后输入验证码并完成。",
            ),
        ]
    )
    runtime, _capture, inputs, events = make_runtime(client, mutate_frames=False)

    state = asyncio.run(runtime.run())

    assert state.status is AgentStatus.FINISHED
    assert inputs.calls == [
        ("click", 41, 0.4, 0.5, {"button": "left"}),
        ("type", 41, "2684"),
    ]
    assert len(client.observations) == 1
    assert not any("中止后续" in event.message for event in events)


def test_multi_step_plan_aborts_remaining_steps_after_failed_scroll() -> None:
    client = SequenceClient(
        [
            decision_from_actions(
                {"type": "scroll", "direction": "down", "amount": 3},
                {"type": "click", "x": 0.6, "y": 0.7},
                summary="先滚动再点击。",
            ),
            decision_from_actions(
                {"type": "finish", "result": "改用其他策略完成"},
                summary="完成。",
            ),
        ]
    )
    runtime, _capture, inputs, events = make_runtime(client, mutate_frames=False)

    state = asyncio.run(runtime.run())

    assert state.status is AgentStatus.FINISHED
    assert len(inputs.calls) == 1
    assert inputs.calls[0][0] == "scroll"
    assert client.observations[1].previous_result is not None
    assert "计划已中止" in client.observations[1].previous_result.message
    assert any(
        event.phase is RuntimePhase.VERIFY and "中止后续" in event.message
        for event in events
    )


def test_parse_decision_wraps_legacy_single_action() -> None:
    decision = parse_decision(
        {
            "type": "finish",
            "result": "done",
            "decision_summary": "连通性测试完成。",
        }
    )
    assert len(decision.actions) == 1
    assert decision.actions[0].type == "finish"
    assert decision.decision_summary == "连通性测试完成。"
