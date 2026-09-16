"""Human-readable, in-memory descriptions of validated AgentAction objects."""

from __future__ import annotations

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
)


def describe_action(action: AgentAction | None) -> str:
    """Describe a validated action for the GUI without serializing requests."""
    if action is None:
        return "尚无动作"
    if isinstance(action, ClickAction):
        button = "左键" if action.button == "left" else "右键"
        return f"单击 x={action.x:.3f}, y={action.y:.3f}, {button}"
    if isinstance(action, DoubleClickAction):
        return f"双击 x={action.x:.3f}, y={action.y:.3f}"
    if isinstance(action, RightClickAction):
        return f"右键单击 x={action.x:.3f}, y={action.y:.3f}"
    if isinstance(action, TypeAction):
        preview = action.text.replace("\r", "\\r").replace("\n", "\\n")
        if len(preview) > 80:
            preview = preview[:77] + "..."
        return f"输入文本“{preview}”（{len(action.text)} 字符）"
    if isinstance(action, HotkeyAction):
        return f"组合键 {'+'.join(action.keys)}"
    if isinstance(action, ScrollAction):
        direction = "向上" if action.direction == "up" else "向下"
        return f"{direction}滚动 {action.amount} 格"
    if isinstance(action, WaitAction):
        return f"等待 {action.milliseconds} 毫秒"
    if isinstance(action, FinishAction):
        return f"完成：{action.result}"
    if isinstance(action, FailAction):
        return f"失败：{action.reason}"
    return f"未知动作：{getattr(action, 'type', type(action).__name__)}"


def describe_decision(action: AgentAction | None) -> str:
    """Return only the validated public decision summary, never hidden reasoning."""
    if action is None or not action.decision_summary:
        return "模型未提供决策说明"
    return action.decision_summary
