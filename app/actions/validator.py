"""Safety validation applied immediately before action execution."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from app.actions.schema import (
    ACTION_MODELS,
    AgentAction,
    ClickAction,
    DoubleClickAction,
    HotkeyAction,
    RightClickAction,
    WaitAction,
)
from app.common.exceptions import ActionValidationError
from app.common.logging import get_logger
from app.windows.models import WindowInfo

DEFAULT_ALLOWED_HOTKEYS = ("CTRL+A", "CTRL+C", "CTRL+V", "CTRL+F", "ENTER")
FORBIDDEN_HOTKEYS = frozenset(("ALT+F4", "WIN", "WIN+R", "CTRL+ALT+DELETE"))
KEY_ALIASES = {"RETURN": "ENTER"}
logger = get_logger(__name__)


class ValidationWindowManager(Protocol):
    def exists(self, hwnd: int) -> bool: ...

    def get_window(self, hwnd: int) -> WindowInfo: ...

    def is_minimized(self, hwnd: int) -> bool: ...


class ActionValidationState(BaseModel):
    """Runtime facts needed to validate one action."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    hwnd: int = Field(gt=0)
    step: int = Field(ge=0)
    max_steps: int = Field(gt=0)
    window: WindowInfo


class ActionValidator:
    """Validate schema, runtime limits, target identity, and hotkey policy."""

    def __init__(
        self,
        window_manager: ValidationWindowManager,
        allowed_hotkeys: Iterable[str] = DEFAULT_ALLOWED_HOTKEYS,
    ) -> None:
        self._window_manager = window_manager
        self._allowed_hotkeys = frozenset(
            self._normalize_hotkey_text(hotkey) for hotkey in allowed_hotkeys
        )

    def validate(
        self,
        action: AgentAction,
        state: ActionValidationState,
    ) -> AgentAction:
        """Return *action* when safe, otherwise raise ActionValidationError."""
        if not isinstance(action, ACTION_MODELS):
            raise ActionValidationError(
                f"Unsupported action object: {type(action).__name__}"
            )
        if state.step >= state.max_steps:
            raise ActionValidationError(
                f"Maximum steps reached: {state.step}/{state.max_steps}"
            )
        if state.window.hwnd != state.hwnd:
            raise ActionValidationError("Validation window does not match target HWND")
        try:
            if not self._window_manager.exists(state.hwnd):
                raise ActionValidationError(
                    f"Target window no longer exists: HWND {state.hwnd}"
                )
            if self._window_manager.is_minimized(state.hwnd):
                raise ActionValidationError(
                    f"Target window is minimized: HWND {state.hwnd}"
                )
            current_window = self._window_manager.get_window(state.hwnd)
        except ActionValidationError:
            raise
        except Exception as exc:
            logger.exception(
                "action_window_validation_failed",
                hwnd=state.hwnd,
                error=str(exc),
            )
            raise ActionValidationError(
                f"Unable to validate target window: HWND {state.hwnd}"
            ) from exc
        self._validate_window_unchanged(state.window, current_window)

        if isinstance(action, (ClickAction, DoubleClickAction, RightClickAction)):
            self._validate_pointer_action(action, current_window)
        elif isinstance(action, WaitAction):
            if not 100 <= action.milliseconds <= 5000:
                raise ActionValidationError("Wait must be between 100 and 5000 ms")
        elif isinstance(action, HotkeyAction):
            self._validate_hotkey(action)
        return action

    @staticmethod
    def _validate_window_unchanged(
        expected: WindowInfo,
        current: WindowInfo,
    ) -> None:
        expected_rect = (expected.left, expected.top, expected.width, expected.height)
        current_rect = (current.left, current.top, current.width, current.height)
        if expected_rect != current_rect:
            raise ActionValidationError(
                "Target window position or size changed before execution"
            )

    @staticmethod
    def _validate_pointer_action(
        action: ClickAction | DoubleClickAction | RightClickAction,
        window: WindowInfo,
    ) -> None:
        if not (0.0 <= action.x <= 1.0 and 0.0 <= action.y <= 1.0):
            raise ActionValidationError("Coordinates must be between 0 and 1")

        offset_x = min(window.width - 1, round(window.width * action.x))
        offset_y = min(window.height - 1, round(window.height * action.y))
        screen_x = window.left + offset_x
        screen_y = window.top + offset_y
        if not (
            window.left <= screen_x < window.left + window.width
            and window.top <= screen_y < window.top + window.height
        ):
            raise ActionValidationError("Pointer coordinates fall outside target window")

    def _validate_hotkey(self, action: HotkeyAction) -> None:
        keys = [self._normalize_key(key) for key in action.keys]
        hotkey = "+".join(keys)
        if hotkey in FORBIDDEN_HOTKEYS or "WIN" in keys:
            raise ActionValidationError(f"Forbidden hotkey: {hotkey}")
        if hotkey not in self._allowed_hotkeys:
            raise ActionValidationError(f"Hotkey is not allowed: {hotkey}")

    @classmethod
    def _normalize_hotkey_text(cls, hotkey: str) -> str:
        return "+".join(
            cls._normalize_key(part)
            for part in hotkey.split("+")
            if part.strip()
        )

    @staticmethod
    def _normalize_key(key: str) -> str:
        normalized = key.strip().upper()
        return KEY_ALIASES.get(normalized, normalized)
