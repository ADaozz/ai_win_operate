from __future__ import annotations

import pytest

from app.actions.executor import ActionExecutor, ValidatedInputService
from app.actions.schema import parse_action
from app.common.exceptions import AgentStoppedError, ActionValidationError
from app.windows.models import WindowInfo


class RecordingInputExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []
        self.failure: Exception | None = None

    def _record(self, *call: object) -> None:
        if self.failure is not None:
            raise self.failure
        self.calls.append(call)

    def click(self, hwnd: int, x: float, y: float, **kwargs: object) -> None:
        self._record("click", hwnd, x, y, kwargs)

    def double_click(self, hwnd: int, x: float, y: float) -> None:
        self._record("double_click", hwnd, x, y)

    def right_click(self, hwnd: int, x: float, y: float) -> None:
        self._record("right_click", hwnd, x, y)

    def type_text(self, hwnd: int, text: str) -> None:
        self._record("type", hwnd, text)

    def hotkey(self, hwnd: int, keys: list[str]) -> None:
        self._record("hotkey", hwnd, keys)

    def scroll(self, hwnd: int, direction: str, amount: int = 3) -> None:
        self._record("scroll", hwnd, direction, amount)


def make_window() -> WindowInfo:
    return WindowInfo(
        hwnd=55,
        title="Target",
        pid=66,
        left=0,
        top=0,
        width=800,
        height=600,
    )


def test_executor_dispatches_input_actions() -> None:
    input_executor = RecordingInputExecutor()
    executor = ActionExecutor(input_executor)
    window = make_window()
    payloads = [
        {"type": "click", "x": 0.1, "y": 0.2, "button": "right"},
        {"type": "double_click", "x": 0.3, "y": 0.4},
        {"type": "right_click", "x": 0.5, "y": 0.6},
        {"type": "type", "text": "Hello"},
        {"type": "hotkey", "keys": ["CTRL", "A"]},
        {"type": "scroll", "direction": "down", "amount": 2},
    ]

    results = [executor.execute(parse_action(payload), window) for payload in payloads]

    assert all(result.success for result in results)
    assert "continue with the next task action" in results[0].message
    assert input_executor.calls == [
        ("click", 55, 0.1, 0.2, {"button": "right"}),
        ("double_click", 55, 0.3, 0.4),
        ("right_click", 55, 0.5, 0.6),
        ("type", 55, "Hello"),
        ("hotkey", 55, ["CTRL", "A"]),
        ("scroll", 55, "down", 2),
    ]


def test_executor_receives_split_hotkey_tokens_from_action_schema() -> None:
    input_executor = RecordingInputExecutor()
    executor = ActionExecutor(input_executor)

    result = executor.execute(
        parse_action({"type": "hotkey", "keys": ["CTRL+A"]}),
        make_window(),
    )

    assert result.success is True
    assert input_executor.calls == [("hotkey", 55, ["CTRL", "A"])]


def test_executor_handles_wait_and_terminal_actions_without_input() -> None:
    input_executor = RecordingInputExecutor()
    sleeps: list[float] = []
    executor = ActionExecutor(input_executor, sleep=sleeps.append)
    window = make_window()

    wait_result = executor.execute(
        parse_action({"type": "wait", "milliseconds": 250}),
        window,
    )
    finish_result = executor.execute(
        parse_action({"type": "finish", "result": "complete"}),
        window,
    )
    fail_result = executor.execute(
        parse_action({"type": "fail", "reason": "impossible"}),
        window,
    )

    assert sleeps == [0.25]
    assert wait_result.success is True
    assert finish_result.message == "complete"
    assert fail_result.message == "impossible"
    assert input_executor.calls == []


def test_executor_converts_input_failure_to_action_result() -> None:
    input_executor = RecordingInputExecutor()
    input_executor.failure = RuntimeError("injected failure")
    clock_values = iter((1.0, 1.125))
    executor = ActionExecutor(input_executor, clock=lambda: next(clock_values))

    result = executor.execute(
        parse_action({"type": "type", "text": "blocked"}),
        make_window(),
    )

    assert result.success is False
    assert result.message == "injected failure"
    assert result.duration_ms == 125


def test_executor_rechecks_emergency_stop_before_dispatch() -> None:
    input_executor = RecordingInputExecutor()
    executor = ActionExecutor(input_executor, stop_requested=lambda: True)

    with pytest.raises(AgentStoppedError, match="stopped"):
        executor.execute(
            parse_action({"type": "click", "x": 0.5, "y": 0.5}),
            make_window(),
        )

    assert input_executor.calls == []


class StableWindowManager:
    def __init__(self, window: WindowInfo) -> None:
        self.window = window

    def exists(self, hwnd: int) -> bool:
        return hwnd == self.window.hwnd

    def get_window(self, hwnd: int) -> WindowInfo:
        assert hwnd == self.window.hwnd
        return self.window

    def is_minimized(self, hwnd: int) -> bool:
        assert hwnd == self.window.hwnd
        return False


def test_validated_input_service_enforces_manual_action_pipeline() -> None:
    window = make_window()
    input_executor = RecordingInputExecutor()
    service = ValidatedInputService(StableWindowManager(window), input_executor)

    service.click(window.hwnd, 0.25, 0.75)
    service.hotkey(window.hwnd, ["CTRL", "A"])

    assert input_executor.calls == [
        ("click", 55, 0.25, 0.75, {"button": "left"}),
        ("hotkey", 55, ["CTRL", "A"]),
    ]

    with pytest.raises(ActionValidationError, match="not allowed"):
        service.hotkey(window.hwnd, ["CTRL", "P"])
    assert len(input_executor.calls) == 2
