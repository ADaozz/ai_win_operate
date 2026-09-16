"""Production construction of one protocol-driven Agent Runtime."""

from __future__ import annotations

import threading
from typing import Protocol

from app.actions.executor import ActionExecutor, InputActionExecutor
from app.actions.validator import ActionValidator, ValidationWindowManager
from app.agent.runtime import (
    AgentRuntime,
    RuntimeCapture,
    RuntimeEventCallback,
    RuntimeFrameCallback,
)
from app.agent.state import AgentState
from app.agent.verifier import LocalResultVerifier
from app.common.exceptions import AgentStoppedError
from app.config.settings import Settings
from app.llm.factory import create_vision_client


class RuntimeFactory(Protocol):
    def create(
        self,
        task: str,
        hwnd: int,
        on_event: RuntimeEventCallback | None = None,
        on_frame: RuntimeFrameCallback | None = None,
        max_steps: int | None = None,
    ) -> AgentRuntime: ...


class DefaultRuntimeFactory:
    """Build isolated runtime dependencies for each Start operation."""

    def __init__(
        self,
        settings: Settings,
        window_manager: ValidationWindowManager,
        capture: RuntimeCapture,
        input_executor: InputActionExecutor,
    ) -> None:
        self._settings = settings
        self._window_manager = window_manager
        self._capture = capture
        self._input_executor = input_executor

    def create(
        self,
        task: str,
        hwnd: int,
        on_event: RuntimeEventCallback | None = None,
        on_frame: RuntimeFrameCallback | None = None,
        max_steps: int | None = None,
    ) -> AgentRuntime:
        stop_event = threading.Event()

        def interruptible_sleep(seconds: float) -> None:
            if stop_event.wait(seconds):
                raise AgentStoppedError("Agent Runtime stopped during wait")

        executor = ActionExecutor(
            self._input_executor,
            sleep=interruptible_sleep,
            stop_requested=stop_event.is_set,
        )
        return AgentRuntime(
            state=AgentState(
                task=task,
                hwnd=hwnd,
                max_steps=max_steps or self._settings.agent_max_steps,
            ),
            window_manager=self._window_manager,
            capture=self._capture,
            llm=create_vision_client(self._settings),
            validator=ActionValidator(
                self._window_manager,
                self._settings.allowed_hotkeys,
            ),
            executor=executor,
            stop_event=stop_event,
            max_repeated_actions=self._settings.agent_max_repeated_actions,
            max_repeated_clicks=self._settings.agent_max_repeated_clicks,
            repeat_recovery_attempts=self._settings.agent_repeat_recovery_attempts,
            click_repeat_recovery_attempts=(
                self._settings.agent_click_repeat_recovery_attempts
            ),
            action_delay_ms=self._settings.agent_action_delay_ms,
            verifier=LocalResultVerifier(
                threshold=self._settings.agent_frame_diff_threshold
            ),
            on_event=on_event,
            on_frame=on_frame,
        )
