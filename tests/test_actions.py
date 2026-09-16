from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.actions.schema import (
    ActionResult,
    ClickAction,
    DoubleClickAction,
    FailAction,
    FinishAction,
    HotkeyAction,
    RightClickAction,
    ScrollAction,
    TypeAction,
    WaitAction,
    action_json_schema,
    decision_json_schema,
    parse_action,
    parse_decision,
)


@pytest.mark.parametrize(
    ("payload", "expected_type"),
    [
        ({"type": "click", "x": 0.2, "y": 0.8}, ClickAction),
        ({"type": "double_click", "x": 0.2, "y": 0.8}, DoubleClickAction),
        ({"type": "right_click", "x": 0.2, "y": 0.8}, RightClickAction),
        ({"type": "type", "text": "hello"}, TypeAction),
        ({"type": "hotkey", "keys": ["CTRL", "A"]}, HotkeyAction),
        ({"type": "scroll", "direction": "down"}, ScrollAction),
        ({"type": "wait"}, WaitAction),
        ({"type": "finish", "result": "done"}, FinishAction),
        ({"type": "fail", "reason": "blocked"}, FailAction),
    ],
)
def test_parse_action_discriminates_every_supported_type(
    payload: dict[str, object],
    expected_type: type,
) -> None:
    action = parse_action(payload)
    assert isinstance(action, expected_type)


def test_parse_action_accepts_strict_json() -> None:
    action = parse_action(
        '{"type":"click","x":0.42,"y":0.67,'
        '"decision_summary":"  题面未显示完整，先定位内容区域。  "}'
    )

    assert isinstance(action, ClickAction)
    assert action.button == "left"
    assert action.decision_summary == "题面未显示完整，先定位内容区域。"


@pytest.mark.parametrize(
    ("keys", "expected"),
    [
        (["CTRL+A"], ["CTRL", "A"]),
        (["ctrl", "a"], ["CTRL", "A"]),
        (["RETURN"], ["ENTER"]),
    ],
)
def test_hotkey_tokens_are_canonicalized(
    keys: list[str],
    expected: list[str],
) -> None:
    action = parse_action({"type": "hotkey", "keys": keys})

    assert isinstance(action, HotkeyAction)
    assert action.keys == expected


@pytest.mark.parametrize(
    "payload",
    [
        {"type": "click", "x": -0.01, "y": 0.5},
        {"type": "click", "x": 0.5, "y": 1.01},
        {"type": "wait", "milliseconds": 99},
        {"type": "wait", "milliseconds": 5001},
        {"type": "hotkey", "keys": []},
        {"type": "hotkey", "keys": ["CTRL++A"]},
        {"type": "shell", "command": "whoami"},
        {"type": "click", "x": 0.5, "y": 0.5, "unexpected": True},
    ],
)
def test_invalid_actions_are_rejected(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        parse_action(payload)


def test_action_schema_exposes_discriminator() -> None:
    schema = action_json_schema()

    assert schema["discriminator"]["propertyName"] == "type"
    assert len(schema["oneOf"]) == 9
    assert "decision_summary" in schema["$defs"]["ClickAction"]["properties"]


def test_decision_summary_has_a_safe_display_limit() -> None:
    with pytest.raises(ValidationError):
        parse_action(
            {
                "type": "wait",
                "milliseconds": 100,
                "decision_summary": "x" * 241,
            }
        )


def test_action_result_is_strict_and_forbids_extra_fields() -> None:
    result = ActionResult(
        success=True,
        message="ok",
        duration_ms=12,
        frame_diff_score=0.12,
        ui_changed=True,
    )
    assert result.success is True
    assert result.ui_changed is True

    with pytest.raises(ValidationError):
        ActionResult.model_validate({"success": 1})
    with pytest.raises(ValidationError):
        ActionResult.model_validate({"success": True, "extra": "no"})


def test_parse_decision_accepts_multi_step_plan() -> None:
    decision = parse_decision(
        {
            "decision_summary": "点击后输入。",
            "actions": [
                {"type": "click", "x": 0.2, "y": 0.3},
                {"type": "type", "text": "hi"},
            ],
        },
        max_actions=5,
    )
    assert len(decision.actions) == 2
    assert decision.actions[0].type == "click"
    assert decision.actions[1].type == "type"


def test_parse_decision_rejects_overlong_plans() -> None:
    with pytest.raises(ValueError, match="maximum allowed is 2"):
        parse_decision(
            {
                "decision_summary": "太多步骤。",
                "actions": [
                    {"type": "wait", "milliseconds": 100},
                    {"type": "wait", "milliseconds": 100},
                    {"type": "wait", "milliseconds": 100},
                ],
            },
            max_actions=2,
        )


def test_decision_schema_exposes_actions_array() -> None:
    schema = decision_json_schema()
    assert "actions" in schema["properties"]
    assert "decision_summary" in schema["properties"]
