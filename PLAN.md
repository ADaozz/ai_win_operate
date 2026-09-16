# Development Plan

按 Milestone 推进；每完成一个阶段并补齐测试与文档后再进入下一阶段。

## 当前状态

- [x] Milestone 0：项目骨架
- [x] Milestone 1：Windows Window Manager
- [x] Milestone 2：窗口截图
- [x] Milestone 3：鼠标键盘 Executor
- [x] Milestone 4：Action Schema + Validator
- [x] Milestone 5：Qwen Vision
- [x] Milestone 6：完整 Agent Loop
- [x] Milestone 7：结果验证（Frame Diff + 多步计划）
- [ ] Milestone 8：UI Automation
- [ ] Milestone 9：变化监控

## Milestone 7 验收项

- Pillow 本地 Frame Diff：灰度缩放后计算平均绝对差，得到 `changed` / `score`
- `LocalResultVerifier` 在 EXECUTE 后比对动作前后截图，不调用第二次模型
- `ActionResult` 与 `Observation` 携带 `frame_diff_score` / `ui_changed` / `frame_diff`
- Runtime 增加 VERIFY 阶段；下一轮 Prompt 使用 Frame Diff 作为权威证据
- 模型输出改为 `AgentDecision`（`decision_summary` + `actions[]`），默认最多 5 步
- 计划内逐步 validate → execute → verify；期望 UI 变化但 score 过低时中止剩余步骤并重新观察
- 兼容旧的单 Action JSON（自动包装为单步计划）；Debug Panel 仍使用 `parse_action`
- 相关 pytest 覆盖 Frame Diff、Verifier、多步中止与 Qwen decision schema

## 下一步

进入 Milestone 8，接入 UI Automation 元素观察。本轮未实现被动监控模式、
独立 Verifier LLM、OpenCV 或压图参数调优。
