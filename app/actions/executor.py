"""Dispatch validated AgentAction objects to the local input executor."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from typing import Protocol

from app.actions.schema import (
    AgentAction,
    ClickAction,
    DoubleClickAction,
    FailAction,
    FinishAction,
    HotkeyAction,
    RightClickAction,
    ScrollAction,
    TypeAction,
    WaitAction,
    ActionResult,
)
from app.actions.validator import (
    DEFAULT_ALLOWED_HOTKEYS,
    ActionValidationState,
    ActionValidator,
    ValidationWindowManager,
)
from app.common.exceptions import AgentStoppedError, InputExecutionError
from app.common.logging import get_logger
from app.windows.models import WindowInfo

logger = get_logger(__name__)


class InputActionExecutor(Protocol):
    def click(
        self,
        hwnd: int,
        x: float,
        y: float,
        **kwargs: object,
    ) -> None: ...

    def double_click(self, hwnd: int, x: float, y: float) -> None: ...

    def right_click(self, hwnd: int, x: float, y: float) -> None: ...

    def type_text(self, hwnd: int, text: str) -> None: ...

    def hotkey(self, hwnd: int, keys: list[str]) -> None: ...

    def scroll(self, hwnd: int, direction: str, amount: int = 3) -> None: ...


class ActionExecutor:
    """Execute one structured action and always return a typed result."""

    def __init__(
        self,
        input_executor: InputActionExecutor,
        *,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.perf_counter,
        stop_requested: Callable[[], bool] | None = None,
    ) -> None:
        self._input_executor = input_executor
        self._sleep = sleep
        self._clock = clock
        self._stop_requested = stop_requested or (lambda: False)

    def execute(
        self,
        action: AgentAction,
        window: WindowInfo,
    ) -> ActionResult:
        if self._stop_requested():
            raise AgentStoppedError("Agent Runtime stopped before action execution")
        started = self._clock()
        try:
            message = self._dispatch(action, window)
            return ActionResult(
                success=True,
                message=message,
                duration_ms=max(0, round((self._clock() - started) * 1000)),
            )
        except AgentStoppedError:
            raise
        except Exception as exc:
            logger.exception(
                "action_execution_failed",
                hwnd=window.hwnd,
                action_type=getattr(action, "type", "unknown"),
                error=str(exc),
            )
            return ActionResult(
                success=False,
                message=str(exc),
                duration_ms=max(0, round((self._clock() - started) * 1000)),
            )

    def _dispatch(self, action: AgentAction, window: WindowInfo) -> str:
        hwnd = window.hwnd
        if isinstance(action, ClickAction):
            self._input_executor.click(
                hwnd,
                action.x,
                action.y,
                button=action.button,
            )
            return "click input delivered successfully; continue with the next task action"
        if isinstance(action, DoubleClickAction):
            self._input_executor.double_click(hwnd, action.x, action.y)
            return "double_click input delivered successfully; continue with the next task action"
        if isinstance(action, RightClickAction):
            self._input_executor.right_click(hwnd, action.x, action.y)
            return "right_click input delivered successfully; continue with the next task action"
        if isinstance(action, TypeAction):
            self._input_executor.type_text(hwnd, action.text)
            return "type executed"
        if isinstance(action, HotkeyAction):
            self._input_executor.hotkey(hwnd, action.keys)
            return "hotkey executed"
        if isinstance(action, ScrollAction):
            self._input_executor.scroll(hwnd, action.direction, action.amount)
            return "scroll executed"
        if isinstance(action, WaitAction):
            self._sleep(action.milliseconds / 1000)
            return "wait completed"
        if isinstance(action, FinishAction):
            return action.result
        if isinstance(action, FailAction):
            return action.reason
        raise TypeError(f"Unsupported action object: {type(action).__name__}")


class ValidatedInputService:
    """Adapt manual debug controls to the mandatory validated action pipeline."""

    def __init__(
        self,
        window_manager: ValidationWindowManager,
        input_executor: InputActionExecutor,
        allowed_hotkeys: Iterable[str] = DEFAULT_ALLOWED_HOTKEYS,
    ) -> None:
        self._window_manager = window_manager
        self._validator = ActionValidator(window_manager, allowed_hotkeys)
        self._executor = ActionExecutor(input_executor)

    def click(
        self,
        hwnd: int,
        x: float,
        y: float,
        **kwargs: object,
    ) -> None:
        button = kwargs.get("button", "left")
        self._execute(
            ClickAction.model_validate(
                {"type": "click", "x": x, "y": y, "button": button}
            ),
            hwnd,
        )

    def double_click(self, hwnd: int, x: float, y: float) -> None:
        self._execute(DoubleClickAction(type="double_click", x=x, y=y), hwnd)

    def right_click(self, hwnd: int, x: float, y: float) -> None:
        self._execute(RightClickAction(type="right_click", x=x, y=y), hwnd)

    def type_text(self, hwnd: int, text: str) -> None:
        self._execute(TypeAction(type="type", text=text), hwnd)

    def hotkey(self, hwnd: int, keys: list[str]) -> None:
        self._execute(HotkeyAction(type="hotkey", keys=keys), hwnd)

    def scroll(self, hwnd: int, direction: str, amount: int = 3) -> None:
        self._execute(
            ScrollAction.model_validate(
                {"type": "scroll", "direction": direction, "amount": amount}
            ),
            hwnd,
        )

    def _execute(self, action: AgentAction, hwnd: int) -> None:
        window = self._window_manager.get_window(hwnd)
        state = ActionValidationState(
            hwnd=hwnd,
            step=0,
            max_steps=1,
            window=window,
        )
        validated = self._validator.validate(action, state)
        result = self._executor.execute(validated, window)
        if not result.success:
            raise InputExecutionError(result.message or "Action execution failed")
