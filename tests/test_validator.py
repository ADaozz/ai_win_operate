from __future__ import annotations

from typing import cast

import pytest

from app.actions.schema import AgentAction, ClickAction, HotkeyAction, WaitAction
from app.actions.validator import ActionValidationState, ActionValidator
from app.common.exceptions import ActionValidationError
from app.windows.models import WindowInfo


def make_window(**changes: int | str) -> WindowInfo:
    values: dict[str, int | str] = {
        "hwnd": 100,
        "title": "Target",
        "pid": 200,
        "left": 10,
        "top": 20,
        "width": 800,
        "height": 600,
    }
    values.update(changes)
    return WindowInfo.model_validate(values)


class FakeWindowManager:
    def __init__(
        self,
        window: WindowInfo,
        *,
        exists: bool = True,
        minimized: bool = False,
    ) -> None:
        self.window = window
        self.window_exists = exists
        self.minimized = minimized

    def exists(self, hwnd: int) -> bool:
        return self.window_exists and hwnd == self.window.hwnd

    def get_window(self, hwnd: int) -> WindowInfo:
        assert hwnd == self.window.hwnd
        return self.window

    def is_minimized(self, hwnd: int) -> bool:
        assert hwnd == self.window.hwnd
        return self.minimized


def make_state(window: WindowInfo | None = None, **changes: int) -> ActionValidationState:
    target = window or make_window()
    values = {
        "hwnd": target.hwnd,
        "step": 0,
        "max_steps": 30,
        "window": target,
    }
    values.update(changes)
    return ActionValidationState.model_validate(values)


def test_validator_accepts_safe_pointer_boundary_and_allowed_hotkey() -> None:
    window = make_window()
    validator = ActionValidator(FakeWindowManager(window))
    state = make_state(window)

    click = ClickAction(type="click", x=1.0, y=1.0)
    assert validator.validate(click, state) is click

    hotkey = HotkeyAction(type="hotkey", keys=["ctrl", "a"])
    assert validator.validate(hotkey, state) is hotkey
    packed_hotkey = HotkeyAction(type="hotkey", keys=["CTRL+A"])
    assert packed_hotkey.keys == ["CTRL", "A"]
    assert validator.validate(packed_hotkey, state) is packed_hotkey

    enter = HotkeyAction(type="hotkey", keys=["return"])
    assert enter.keys == ["ENTER"]
    assert validator.validate(enter, state) is enter


def test_validator_rejects_missing_or_minimized_window() -> None:
    window = make_window()

    with pytest.raises(ActionValidationError, match="no longer exists"):
        ActionValidator(FakeWindowManager(window, exists=False)).validate(
            ClickAction(type="click", x=0.5, y=0.5),
            make_state(window),
        )

    with pytest.raises(ActionValidationError, match="minimized"):
        ActionValidator(FakeWindowManager(window, minimized=True)).validate(
            ClickAction(type="click", x=0.5, y=0.5),
            make_state(window),
        )


def test_validator_rejects_window_rect_change() -> None:
    observed = make_window()
    moved = make_window(left=11)
    validator = ActionValidator(FakeWindowManager(moved))

    with pytest.raises(ActionValidationError, match="position or size changed"):
        validator.validate(
            ClickAction(type="click", x=0.5, y=0.5),
            make_state(observed),
        )


def test_validator_converts_window_inspection_failure() -> None:
    class FailingManager(FakeWindowManager):
        def get_window(self, hwnd: int) -> WindowInfo:
            raise RuntimeError("access denied")

    window = make_window()
    validator = ActionValidator(FailingManager(window))

    with pytest.raises(ActionValidationError, match="Unable to validate"):
        validator.validate(
            ClickAction(type="click", x=0.5, y=0.5),
            make_state(window),
        )


def test_validator_rejects_maximum_step() -> None:
    window = make_window()
    validator = ActionValidator(FakeWindowManager(window))

    with pytest.raises(ActionValidationError, match="Maximum steps"):
        validator.validate(
            ClickAction(type="click", x=0.5, y=0.5),
            make_state(window, step=30, max_steps=30),
        )


@pytest.mark.parametrize(
    "keys",
    [
        ["ALT", "F4"],
        ["ALT+F4"],
        ["WIN"],
        ["WIN", "R"],
        ["CTRL", "ALT", "DELETE"],
        ["CTRL", "P"],
    ],
)
def test_validator_rejects_forbidden_or_unlisted_hotkey(keys: list[str]) -> None:
    window = make_window()
    validator = ActionValidator(FakeWindowManager(window))

    with pytest.raises(ActionValidationError, match="hotkey|Hotkey"):
        validator.validate(
            HotkeyAction(type="hotkey", keys=keys),
            make_state(window),
        )


def test_validator_defends_against_models_constructed_without_validation() -> None:
    window = make_window()
    validator = ActionValidator(FakeWindowManager(window))
    state = make_state(window)

    invalid_click = ClickAction.model_construct(type="click", x=2.0, y=0.5)
    with pytest.raises(ActionValidationError, match="between 0 and 1"):
        validator.validate(invalid_click, state)

    invalid_wait = WaitAction.model_construct(type="wait", milliseconds=10)
    with pytest.raises(ActionValidationError, match="between 100 and 5000"):
        validator.validate(invalid_wait, state)

    with pytest.raises(ActionValidationError, match="Unsupported action"):
        validator.validate(cast(AgentAction, object()), state)
