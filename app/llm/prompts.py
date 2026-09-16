"""用于选择一个或多个安全结构化 GUI 动作的提示词。"""

from __future__ import annotations

import json

from app.agent.observation import Observation

SYSTEM_PROMPT = """你是 Windows GUI 控制智能体。

你只能操作当前提供的目标窗口。

你会收到：

- 用户目标
- 当前截图
- 目标窗口信息
- 可用的 UI Automation 元素
- 上一步动作
- 上一步动作结果
- 上一轮 frame_diff（上一步执行后的本地像素变化分数）

你的任务是返回一个简短计划，包含一个或多个下一步动作。

规则：

1. 绝不操作目标窗口之外的区域。
2. 返回一个 JSON 对象，包含 decision_summary 与 actions（1 到 N 个动作）。
3. 若有可见的 UI Automation 元素，优先使用它们。
4. 否则根据截图推断目标位置。
5. 坐标相对目标窗口归一化。
6. x 与 y 必须在 0 到 1 之间。
7. 若界面仍在加载，使用 wait。
8. 若任务已完成，以 finish 结束计划。
9. 若无法安全完成，以 fail 结束计划。
10. 避免重复执行没有带来状态变化的动作。
11. 不确定时，绝不猜测破坏性操作。
12. 选择下一步动作前，先确认上一步是否成功。
13. 若上一步结果显示重复动作已被跳过，必须更换坐标或动作类型，或返回 fail；
    不得重复被拦截的动作。
14. 成功的 click 结果表示指针输入已送达。不要仅为聚焦而再次点击完全相同的位置；
    若目标是编辑框或输入框，应继续使用 type 或允许的快捷键。
15. 被拦截的上一步动作在下一次决策中禁止再次出现；返回相同的动作 JSON 无效且不会执行。
16. 提交动作前，先判断当前可见上下文对本任务是否足够。若相关内容被截断、位于视口外、
    折叠、在其他标签页，或仍在加载，应先用 scroll、click 或 wait 等安全动作获取上下文。
17. 按实际场景调整观察方式：所需上下文已经完整时不要机械滚动；相关说明、示例、约束、
    表单字段、警告或结果尚未出现时，不要开始编辑或提交。
18. decision_summary 必须是一句简洁、可展示给用户的说明，概括当前观察到的内容，以及
    本计划为何能推进任务。这是公开决策说明，不是隐藏思维链。尽量使用任务所用语言。
19. 鼠标滚轮作用于指针下方的 UI 区域。若窗口有多个可滚动区域，必要时先在同一计划或
    下一轮决策中用安全 click 把指针放到相关区域，再滚动。
20. 计划结束后，把 frame_diff 当作软证据。分数偏低可能表示未点中、仅为聚焦点击、
    小复选框、绘制延迟，或截图发生在界面刷新之前。当上一步输入已成功送达时，不要仅因
    frame_diff 偏低就把每次决策都收成单个动作。
21. 只要当前截图已经能确定多个连续动作，就优先返回多步计划（例如：聚焦/点击输入框 →
    type → 勾选协议 → 点击提交，或 click 后 type）。把这些动作放进同一个 actions 数组。
    仅当下一步依赖尚未出现的界面（例如需要等导航或菜单打开后再看）时，才提前结束本轮计划。
"""


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def build_user_prompt(observation: Observation) -> str:
    """只渲染观察元数据；图片字节作为独立 content part 发送。"""
    previous_action = (
        observation.previous_action.model_dump(mode="json")
        if observation.previous_action is not None
        else None
    )
    previous_result = (
        observation.previous_result.model_dump(mode="json")
        if observation.previous_result is not None
        else None
    )
    frame_diff = (
        observation.frame_diff.model_dump(mode="json")
        if observation.frame_diff is not None
        else None
    )
    recovery_instruction = _recovery_instruction(observation)
    return f"""任务：

{observation.task}

当前步骤：

{observation.step}

目标窗口：

{_json(observation.window.model_dump(mode="json"))}

UI 元素：

{_json(observation.ui_elements)}

上一步动作：

{_json(previous_action)}

上一步结果：

{_json(previous_result)}

上一轮 frame_diff：

{_json(frame_diff)}

下一步强制约束：

{recovery_instruction}

请返回下一步 GUI 动作计划。"""


def _recovery_instruction(observation: Observation) -> str:
    action = observation.previous_action
    result = observation.previous_result
    if action is None or result is None:
        return "无额外约束。"
    if not result.success and "重复动作已跳过" in result.message:
        return (
            "上一个动作已被禁止，且并未执行。"
            "现在必须返回结构不同的动作。对指针类动作，请改变动作类型，或至少改变 "
            "x/y/button 之一。若没有可安全推进任务的替代方案，请返回 fail。"
            "禁止再次返回相同的动作 JSON。"
        )
    if (
        result.ui_changed is False
        and action.type in {"click", "double_click", "right_click", "scroll"}
    ):
        return (
            "上一步之后本地 frame_diff 偏低。请优先把当前截图里已经能确定的步骤打成多步计划。"
            "仅当截图仍停留在上一屏、且同一次点击明显未命中时，才更换策略。"
            "后续表单步骤已经可见时，不要只返回单个动作。"
        )
    if result.success and action.type in {"click", "double_click", "right_click"}:
        return (
            "上一步指针输入已成功送达。不要再次返回完全相同的指针动作。"
            "请用 type、允许的快捷键、界面加载中的 wait，或真正不同的目标/动作继续任务。"
            "优先把剩余可见步骤打包进同一个计划。"
        )
    return "请把上一步结果与 frame_diff 当作下一轮计划的软证据。"
