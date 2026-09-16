"""Strict, discriminated GUI action models."""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    field_validator,
)


class ActionModel(BaseModel):
    """Base configuration shared by all model-generated actions."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    decision_summary: str = Field(default="", max_length=240)

    @field_validator("decision_summary")
    @classmethod
    def normalize_decision_summary(cls, value: str) -> str:
        """Keep the public rationale concise and safe for one-line GUI display."""
        return " ".join(value.split())


class ClickAction(ActionModel):
    type: Literal["click"]
    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)
    button: Literal["left", "right"] = "left"


class DoubleClickAction(ActionModel):
    type: Literal["double_click"]
    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)


class RightClickAction(ActionModel):
    type: Literal["right_click"]
    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)


class TypeAction(ActionModel):
    type: Literal["type"]
    text: str


class HotkeyAction(ActionModel):
    type: Literal["hotkey"]
    keys: list[str] = Field(min_length=1)

    @field_validator("keys", mode="before")
    @classmethod
    def split_combined_hotkey_tokens(cls, value: Any) -> Any:
        """Accept provider shorthand while preserving one key per array element."""
        if not isinstance(value, list):
            return value
        flattened: list[Any] = []
        for key in value:
            if isinstance(key, str) and "+" in key:
                flattened.extend(key.split("+"))
            else:
                flattened.append(key)
        return flattened

    @field_validator("keys")
    @classmethod
    def normalize_hotkey_keys(cls, keys: list[str]) -> list[str]:
        normalized: list[str] = []
        for key in keys:
            token = key.strip().upper()
            if not token:
                raise ValueError("Hotkey keys must not be blank")
            normalized.append("ENTER" if token == "RETURN" else token)
        return normalized


class ScrollAction(ActionModel):
    type: Literal["scroll"]
    direction: Literal["up", "down"]
    amount: int = Field(default=3, ge=1)


class WaitAction(ActionModel):
    type: Literal["wait"]
    milliseconds: int = Field(default=500, ge=100, le=5000)


class FinishAction(ActionModel):
    type: Literal["finish"]
    result: str


class FailAction(ActionModel):
    type: Literal["fail"]
    reason: str


AgentAction = Annotated[
    ClickAction
    | DoubleClickAction
    | RightClickAction
    | TypeAction
    | HotkeyAction
    | ScrollAction
    | WaitAction
    | FinishAction
    | FailAction,
    Field(discriminator="type"),
]

ACTION_ADAPTER: TypeAdapter[AgentAction] = TypeAdapter(AgentAction)
ACTION_MODELS = (
    ClickAction,
    DoubleClickAction,
    RightClickAction,
    TypeAction,
    HotkeyAction,
    ScrollAction,
    WaitAction,
    FinishAction,
    FailAction,
)


class ActionResult(BaseModel):
    """Outcome of dispatching one validated action."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    success: bool
    message: str = ""
    duration_ms: int = Field(default=0, ge=0)
    frame_diff_score: float | None = Field(default=None, ge=0.0, le=1.0)
    ui_changed: bool | None = None


class AgentDecision(BaseModel):
    """One model response: a public rationale plus one or more GUI actions."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    decision_summary: str = Field(min_length=1, max_length=240)
    actions: list[AgentAction] = Field(min_length=1)

    @field_validator("decision_summary")
    @classmethod
    def normalize_decision_summary(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("decision_summary must not be blank")
        return normalized


DECISION_ADAPTER: TypeAdapter[AgentDecision] = TypeAdapter(AgentDecision)


def parse_action(data: str | bytes | bytearray | dict[str, Any]) -> AgentAction:
    """Parse an action using Pydantic/JSON Schema, never free-text extraction."""
    if isinstance(data, (str, bytes, bytearray)):
        return ACTION_ADAPTER.validate_json(data)
    return ACTION_ADAPTER.validate_python(data)


def parse_decision(
    data: str | bytes | bytearray | dict[str, Any],
    *,
    max_actions: int | None = None,
) -> AgentDecision:
    """Parse a multi-action decision, wrapping a legacy single action when needed."""
    if isinstance(data, (str, bytes, bytearray)):
        raw: Any = json.loads(data)
    else:
        raw = data
    if not isinstance(raw, dict):
        raise ValueError("AgentDecision payload must be an object")
    if "actions" in raw:
        decision = DECISION_ADAPTER.validate_python(raw)
    else:
        action = parse_action(raw)
        summary = action.decision_summary or "模型返回了单个动作。"
        decision = AgentDecision(decision_summary=summary, actions=[action])
    if max_actions is not None and len(decision.actions) > max_actions:
        raise ValueError(
            f"AgentDecision has {len(decision.actions)} actions; "
            f"maximum allowed is {max_actions}"
        )
    return decision


def action_json_schema() -> dict[str, Any]:
    """Return the single-action schema used by Debug Panel and docs."""
    return ACTION_ADAPTER.json_schema()


def decision_json_schema() -> dict[str, Any]:
    """Return the multi-action decision schema supplied to model APIs."""
    return DECISION_ADAPTER.json_schema()
