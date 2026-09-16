from __future__ import annotations

import pytest

from app.actions.presentation import describe_action, describe_decision
from app.actions.schema import parse_action


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"type": "click", "x": 0.1234, "y": 0.5678}, "单击 x=0.123, y=0.568"),
        ({"type": "double_click", "x": 0.1, "y": 0.2}, "双击 x=0.100"),
        ({"type": "right_click", "x": 0.3, "y": 0.4}, "右键单击"),
        ({"type": "type", "text": "第一行\n第二行"}, "第一行\\n第二行"),
        ({"type": "hotkey", "keys": ["CTRL", "A"]}, "CTRL+A"),
        ({"type": "scroll", "direction": "down", "amount": 3}, "向下滚动 3 格"),
        ({"type": "wait", "milliseconds": 500}, "等待 500 毫秒"),
        ({"type": "finish", "result": "任务完成"}, "完成：任务完成"),
        ({"type": "fail", "reason": "无法完成"}, "失败：无法完成"),
    ],
)
def test_describe_action_exposes_validated_action_details(
    payload: dict[str, object],
    expected: str,
) -> None:
    assert expected in describe_action(parse_action(payload))


def test_describe_decision_exposes_only_validated_summary() -> None:
    action = parse_action(
        {
            "type": "scroll",
            "direction": "down",
            "decision_summary": "当前区域内容被截断，先继续查看。",
        }
    )

    assert describe_decision(action) == "当前区域内容被截断，先继续查看。"
    assert describe_decision(parse_action({"type": "wait"})) == "模型未提供决策说明"
