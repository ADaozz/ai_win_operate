"""Cancelable OBSERVE/DECIDE/VALIDATE/EXECUTE/VERIFY Agent Runtime."""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from PIL import Image

from app.actions.executor import ActionExecutor
from app.actions.presentation import describe_action
from app.actions.schema import (
    ActionResult,
    AgentDecision,
    ClickAction,
    DoubleClickAction,
    FailAction,
    FinishAction,
    RightClickAction,
)
from app.actions.validator import ActionValidationState, ActionValidator
from app.agent.observation import Observation
from app.agent.state import AgentState, AgentStatus, TERMINAL_STATUSES
from app.agent.verifier import LocalResultVerifier
from app.common.exceptions import (
    ActionValidationError,
    AgentStoppedError,
    RepeatedActionError,
)
from app.common.logging import get_logger
from app.llm.client import VisionAgentClient
from app.vision.frame_diff import (
    DEFAULT_FRAME_DIFF_THRESHOLD,
    FrameDiffResult,
)
from app.windows.models import WindowInfo

logger = get_logger(__name__)


class RuntimeWindowManager(Protocol):
    def get_window(self, hwnd: int) -> WindowInfo: ...


class RuntimeCapture(Protocol):
    def capture(self, hwnd: int) -> Image.Image: ...


class RuntimePhase(str, Enum):
    STATUS = "status"
    OBSERVE = "observe"
    DECIDE = "decide"
    VALIDATE = "validate"
    EXECUTE = "execute"
    VERIFY = "verify"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class RuntimeEvent:
    phase: RuntimePhase
    status: AgentStatus
    step: int
    max_steps: int
    action_type: str | None = None
    action_detail: str = ""
    decision_summary: str = ""
    success: bool | None = None
    message: str = ""


RuntimeEventCallback = Callable[[RuntimeEvent], None]
RuntimeFrameCallback = Callable[[Image.Image], None]


class AgentRuntime:
    """Run one task while preserving the validated Windows input boundary."""

    def __init__(
        self,
        state: AgentState,
        window_manager: RuntimeWindowManager,
        capture: RuntimeCapture,
        llm: VisionAgentClient,
        validator: ActionValidator,
        executor: ActionExecutor,
        *,
        stop_event: threading.Event | None = None,
        max_repeated_actions: int = 3,
        max_repeated_clicks: int = 5,
        repeat_recovery_attempts: int = 3,
        click_repeat_recovery_attempts: int = 8,
        action_delay_ms: int = 500,
        frame_diff_threshold: float = DEFAULT_FRAME_DIFF_THRESHOLD,
        verifier: LocalResultVerifier | None = None,
        on_event: RuntimeEventCallback | None = None,
        on_frame: RuntimeFrameCallback | None = None,
    ) -> None:
        if max_repeated_actions <= 0:
            raise ValueError("max_repeated_actions must be positive")
        if max_repeated_clicks <= 0:
            raise ValueError("max_repeated_clicks must be positive")
        if repeat_recovery_attempts <= 0:
            raise ValueError("repeat_recovery_attempts must be positive")
        if click_repeat_recovery_attempts <= 0:
            raise ValueError("click_repeat_recovery_attempts must be positive")
        if action_delay_ms < 0:
            raise ValueError("action_delay_ms cannot be negative")
        self._state = state
        self._window_manager = window_manager
        self._capture = capture
        self._llm = llm
        self._validator = validator
        self._executor = executor
        self._stop_event = stop_event or threading.Event()
        self._resume_event = threading.Event()
        self._resume_event.set()
        self._max_repeated_actions = max_repeated_actions
        self._max_repeated_clicks = max_repeated_clicks
        self._repeat_recovery_limit = repeat_recovery_attempts
        self._click_repeat_recovery_limit = click_repeat_recovery_attempts
        self._repeat_recovery_attempts = 0
        self._action_delay = action_delay_ms / 1000
        self._verifier = verifier or LocalResultVerifier(
            threshold=frame_diff_threshold
        )
        self._on_event = on_event
        self._on_frame = on_frame
        self._lock = threading.RLock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._decision_task: asyncio.Task[object] | None = None
        self._last_fingerprint: str | None = None
        self._repeated_actions = 0
        self._last_frame_diff: FrameDiffResult | None = None

    @property
    def state(self) -> AgentState:
        """Return an isolated state snapshot safe to read across threads."""
        with self._lock:
            return self._state.model_copy(deep=True)

    @property
    def stop_event(self) -> threading.Event:
        return self._stop_event

    def pause(self) -> bool:
        with self._lock:
            if self._state.status is not AgentStatus.RUNNING:
                return False
            self._state.status = AgentStatus.PAUSED
            self._state.message = "已暂停"
            self._resume_event.clear()
            event = self._event(RuntimePhase.STATUS, "已暂停")
        self._emit(event)
        return True

    def resume(self) -> bool:
        with self._lock:
            if self._state.status is not AgentStatus.PAUSED:
                return False
            self._state.status = AgentStatus.RUNNING
            self._state.message = "继续运行"
            self._resume_event.set()
            event = self._event(RuntimePhase.STATUS, "继续运行")
        self._emit(event)
        return True

    def stop(self) -> bool:
        with self._lock:
            if self._state.status in TERMINAL_STATUSES:
                return False
            self._stop_event.set()
            self._resume_event.set()
            self._state.status = AgentStatus.STOPPED
            self._state.message = "用户已停止"
            event = self._event(RuntimePhase.STATUS, "用户已停止")
            loop = self._loop
            decision_task = self._decision_task
        self._emit(event)
        if loop is not None and decision_task is not None and not decision_task.done():
            loop.call_soon_threadsafe(decision_task.cancel)
        return True

    async def run(self) -> AgentState:
        """Run until finish, fail, stop, or a configured safety limit."""
        self._loop = asyncio.get_running_loop()
        if self._stop_event.is_set():
            self._set_terminal(AgentStatus.STOPPED, "用户已停止")
            return self.state
        self._set_status(AgentStatus.RUNNING, "开始运行")

        try:
            while await self._wait_until_runnable():
                current = self.state
                if current.step >= current.max_steps:
                    self._set_terminal(AgentStatus.FAILED, "已达到最大步骤数")
                    break

                action_step = current.step + 1
                window = self._window_manager.get_window(current.hwnd)
                self._emit(
                    self._event(
                        RuntimePhase.OBSERVE,
                        "正在截取目标窗口",
                        step_number=action_step,
                    )
                )
                screenshot = self._capture.capture(window.hwnd)
                self._emit_frame(screenshot)
                observation = Observation(
                    task=current.task,
                    step=current.step,
                    window=window,
                    ui_elements=[],
                    previous_action=current.last_action,
                    previous_result=current.last_result,
                    frame_diff=self._last_frame_diff,
                )

                self._raise_if_stopped()
                self._emit(
                    self._event(
                        RuntimePhase.DECIDE,
                        "正在请求模型决策",
                        step_number=action_step,
                    )
                )
                decision_task = asyncio.create_task(
                    self._llm.decide(observation, screenshot)
                )
                with self._lock:
                    self._decision_task = decision_task
                try:
                    decision = await decision_task
                finally:
                    with self._lock:
                        self._decision_task = None

                if not isinstance(decision, AgentDecision):
                    raise TypeError("VisionAgentClient.decide must return AgentDecision")
                plan_summary = decision.decision_summary
                self._emit(
                    self._event(
                        RuntimePhase.DECIDE,
                        f"已获取计划（{len(decision.actions)} 步）",
                        action_detail=describe_action(decision.actions[0]),
                        decision_summary=plan_summary,
                        step_number=action_step,
                    )
                )

                terminal = await self._execute_plan(
                    decision,
                    before_screenshot=screenshot,
                    plan_summary=plan_summary,
                )
                if terminal:
                    break
        except asyncio.CancelledError:
            if not self._stop_event.is_set():
                raise
            self._set_terminal(AgentStatus.STOPPED, "用户已停止")
        except AgentStoppedError:
            self._set_terminal(AgentStatus.STOPPED, "用户已停止")
        except RepeatedActionError as exc:
            self._set_terminal(AgentStatus.FAILED, str(exc))
        except Exception as exc:
            logger.exception(
                "agent_runtime_failed",
                hwnd=self.state.hwnd,
                step=self.state.step,
                error_type=type(exc).__name__,
            )
            self._set_terminal(AgentStatus.FAILED, self._safe_error_message(exc))
        finally:
            self._loop = None
        return self.state

    async def _execute_plan(
        self,
        decision: AgentDecision,
        *,
        before_screenshot: Image.Image,
        plan_summary: str,
    ) -> bool:
        """Execute planned actions; return True when the runtime should stop."""
        remaining = list(decision.actions)
        current_before = before_screenshot
        while remaining:
            if not await self._wait_until_runnable():
                return True
            current = self.state
            if current.step >= current.max_steps:
                self._set_terminal(AgentStatus.FAILED, "已达到最大步骤数")
                return True

            action = remaining.pop(0)
            action_step = current.step + 1
            window = self._window_manager.get_window(current.hwnd)
            action_detail = describe_action(action)
            decision_summary = plan_summary

            self._raise_if_stopped()
            self._track_repeated_action(action)
            repeat_limit = self._repeat_limit(action)
            if self._repeated_actions >= repeat_limit:
                self._repeat_recovery_attempts += 1
                recovery_limit = self._recovery_limit_for(action)
                result = ActionResult(
                    success=False,
                    message=(
                        "重复动作已跳过且未执行；下一步禁止返回相同 Action JSON，"
                        "必须改变动作类型、坐标或按钮，无法推进时请返回 fail"
                    ),
                )
                self._record_step(action, result)
                self._last_frame_diff = None
                self._emit(
                    self._event(
                        RuntimePhase.BLOCKED,
                        result.message,
                        action_type=action.type,
                        action_detail=action_detail,
                        decision_summary=decision_summary,
                        success=False,
                        step_number=action_step,
                    )
                )
                if self._repeat_recovery_attempts >= recovery_limit:
                    raise RepeatedActionError(
                        f"模型在 {recovery_limit} 次恢复机会后仍重复同一动作"
                    )
                if self._action_delay:
                    await self._interruptible_delay(self._action_delay)
                return False

            self._emit(
                self._event(
                    RuntimePhase.VALIDATE,
                    "正在验证动作安全性",
                    action_type=action.type,
                    action_detail=action_detail,
                    decision_summary=decision_summary,
                    step_number=action_step,
                )
            )
            validation_state = ActionValidationState(
                hwnd=current.hwnd,
                step=current.step,
                max_steps=current.max_steps,
                window=window,
            )
            try:
                validated = self._validator.validate(action, validation_state)
            except ActionValidationError as exc:
                result = ActionResult(success=False, message=str(exc))
                self._record_step(action, result)
                self._last_frame_diff = None
                self._emit(
                    self._event(
                        RuntimePhase.BLOCKED,
                        f"安全验证拒绝：{exc}",
                        action_type=action.type,
                        action_detail=action_detail,
                        decision_summary=decision_summary,
                        success=False,
                        step_number=action_step,
                    )
                )
                raise

            self._raise_if_stopped()
            self._emit(
                self._event(
                    RuntimePhase.EXECUTE,
                    "正在执行已验证动作",
                    action_type=validated.type,
                    action_detail=action_detail,
                    decision_summary=decision_summary,
                    step_number=action_step,
                )
            )
            result = self._executor.execute(validated, window)

            if isinstance(validated, (FinishAction, FailAction)):
                self._record_step(validated, result)
                self._last_frame_diff = None
                if isinstance(validated, FinishAction):
                    execution_message = "模型声明任务完成"
                else:
                    execution_message = "模型声明任务失败"
                self._emit(
                    self._event(
                        RuntimePhase.EXECUTE,
                        execution_message,
                        action_type=validated.type,
                        action_detail=action_detail,
                        decision_summary=decision_summary,
                        success=result.success,
                        step_number=action_step,
                    )
                )
                if isinstance(validated, FinishAction):
                    self._set_terminal(AgentStatus.FINISHED, validated.result)
                else:
                    self._set_terminal(AgentStatus.FAILED, validated.reason)
                return True

            if result.success:
                execution_message = "输入已发送；正在进行本地 Frame Diff 校验"
            else:
                execution_message = "输入发送失败"
            self._emit(
                self._event(
                    RuntimePhase.EXECUTE,
                    execution_message,
                    action_type=validated.type,
                    action_detail=action_detail,
                    decision_summary=decision_summary,
                    success=result.success,
                    step_number=action_step,
                )
            )

            self._raise_if_stopped()
            self._emit(
                self._event(
                    RuntimePhase.VERIFY,
                    "等待界面稳定后比对截图",
                    action_type=validated.type,
                    action_detail=action_detail,
                    decision_summary=decision_summary,
                    step_number=action_step,
                )
            )
            # Capture after settle so Frame Diff sees paint/navigation, not the pre-frame.
            if self._action_delay:
                await self._interruptible_delay(self._action_delay)
            after_screenshot = self._capture.capture(window.hwnd)
            self._emit_frame(after_screenshot)
            result, frame_diff = self._verifier.verify(
                validated,
                result,
                current_before,
                after_screenshot,
            )
            abort_plan = self._verifier.should_abort_plan(validated, result)
            aborted_remaining = 0
            if remaining and abort_plan:
                aborted_remaining = len(remaining)
                result = ActionResult(
                    success=result.success,
                    message=(
                        f"{result.message}; "
                        f"计划已中止，未执行后续 {aborted_remaining} 步"
                    ),
                    duration_ms=result.duration_ms,
                    frame_diff_score=result.frame_diff_score,
                    ui_changed=result.ui_changed,
                )
                remaining.clear()
            self._record_step(validated, result)
            self._last_frame_diff = frame_diff
            verify_message = (
                f"frame_diff score={frame_diff.score:.4f}, "
                f"changed={frame_diff.changed}"
            )
            if aborted_remaining:
                verify_message = (
                    f"{verify_message}; 已中止后续 {aborted_remaining} 步并重新观察"
                )
            self._emit(
                self._event(
                    RuntimePhase.VERIFY,
                    verify_message,
                    action_type=validated.type,
                    action_detail=action_detail,
                    decision_summary=decision_summary,
                    success=result.success,
                    step_number=action_step,
                )
            )

            if not result.success or abort_plan:
                return False

            current_before = after_screenshot
        return False

    async def aclose(self) -> None:
        """Close an owned async model client when it exposes ``aclose``."""
        close = getattr(self._llm, "aclose", None)
        if close is not None:
            await close()

    async def _wait_until_runnable(self) -> bool:
        while True:
            self._raise_if_stopped()
            status = self.state.status
            if status is AgentStatus.RUNNING:
                return True
            if status in TERMINAL_STATUSES:
                return False
            await asyncio.sleep(0.05)

    async def _interruptible_delay(self, seconds: float) -> None:
        deadline = asyncio.get_running_loop().time() + seconds
        while True:
            self._raise_if_stopped()
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                return
            await asyncio.sleep(min(0.05, remaining))

    def _raise_if_stopped(self) -> None:
        if self._stop_event.is_set():
            raise AgentStoppedError("Agent Runtime stopped")

    def _track_repeated_action(self, action: object) -> None:
        payload = action.model_dump(  # type: ignore[attr-defined]
            mode="json",
            exclude={"decision_summary"},
        )
        fingerprint = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        if fingerprint == self._last_fingerprint:
            self._repeated_actions += 1
        else:
            self._last_fingerprint = fingerprint
            self._repeated_actions = 1
            self._repeat_recovery_attempts = 0

    def _repeat_limit(self, action: object) -> int:
        if isinstance(action, (ClickAction, DoubleClickAction, RightClickAction)):
            return self._max_repeated_clicks
        return self._max_repeated_actions

    def _recovery_limit_for(self, action: object) -> int:
        if isinstance(action, (ClickAction, DoubleClickAction, RightClickAction)):
            return self._click_repeat_recovery_limit
        return self._repeat_recovery_limit

    def _record_step(self, action: object, result: ActionResult) -> None:
        with self._lock:
            self._state.last_action = action  # type: ignore[assignment]
            self._state.last_result = result
            self._state.step += 1

    def _set_terminal(self, status: AgentStatus, message: str) -> None:
        with self._lock:
            if self._state.status in TERMINAL_STATUSES and self._state.status is not status:
                return
            self._state.status = status
            self._state.message = message
            self._resume_event.set()
            event = self._event(RuntimePhase.STATUS, message)
        self._emit(event)

    def _set_status(self, status: AgentStatus, message: str) -> None:
        with self._lock:
            if self._state.status in TERMINAL_STATUSES:
                return
            self._state.status = status
            self._state.message = message
            event = self._event(RuntimePhase.STATUS, message)
        self._emit(event)

    def _event(
        self,
        phase: RuntimePhase,
        message: str,
        *,
        action_type: str | None = None,
        action_detail: str = "",
        decision_summary: str = "",
        success: bool | None = None,
        step_number: int | None = None,
    ) -> RuntimeEvent:
        current = self._state
        return RuntimeEvent(
            phase=phase,
            status=current.status,
            step=current.step if step_number is None else step_number,
            max_steps=current.max_steps,
            action_type=action_type,
            action_detail=action_detail,
            decision_summary=decision_summary,
            success=success,
            message=message,
        )

    def _emit(self, event: RuntimeEvent) -> None:
        if self._on_event is None:
            return
        try:
            self._on_event(event)
        except Exception:
            logger.exception("agent_runtime_event_callback_failed")

    def _emit_frame(self, screenshot: Image.Image) -> None:
        if self._on_frame is None:
            return
        try:
            self._on_frame(screenshot)
        except Exception:
            logger.exception("agent_runtime_frame_callback_failed")

    @staticmethod
    def _safe_error_message(exc: Exception) -> str:
        message = str(exc).strip()
        return message[:300] if message else type(exc).__name__
