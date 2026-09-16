# Windows GUI Agent

用自然语言驱动 Windows 桌面操作的 Vision Agent。

选择目标窗口、描述任务，Agent 会自动截图、调用视觉大模型决策，并安全地执行鼠标键盘操作——支持暂停 / 继续 / 停止、全局 **F8** 急停、多步计划与本地 Frame Diff 校验。

---

## 特性

- **窗口级操作**：按 HWND 锁定目标窗口，避免误点其他应用
- **Vision 决策**：截图 + 任务描述 → OpenAI 兼容视觉模型输出结构化动作
- **多步计划**：单轮模型响应最多连续执行多步动作，减少往返延迟
- **安全校验**：坐标、等待时间、热键白名单；执行后 Frame Diff 验证界面是否变化
- **可控运行**：暂停 / 继续 / 停止；全局 F8 急停

## 环境要求

| 项目 | 要求 |
|------|------|
| 系统 | Windows 10 / 11 |
| Python | 3.13 |

> 依赖 `pywin32` 与 Windows 输入 API，请在本机 Windows 环境运行，不支持在 WSL / Linux 中完整启动 GUI Agent。

## 快速开始

### 1. 创建虚拟环境并安装

```powershell
cd D:\pycode\ai_operate
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

### 2. 配置环境变量

```powershell
copy .env.example .env
```

按需编辑 `.env`，至少配置 LLM Gateway（OpenAI 兼容接口）：

| 变量 | 说明 |
|------|------|
| `WGA_LLM_PROVIDER` | 固定为 `openai_compatible` |
| `WGA_LLM_MODEL` | 模型名，如 `qwen3.7-plus` |
| `WGA_LLM_BASE_URL` | 接口地址，如 `http://127.0.0.1:8000/v1` |
| `WGA_LLM_AUTH_MODE` | `none` 或 `bearer` |
| `WGA_LLM_API_KEY` | API Key（`bearer` 时需要；兼容 `DASHSCOPE_API_KEY`） |

### 3. 启动

```powershell
python -m app.main
# 或
windows-gui-agent
```

## 使用方式

1. 在窗口列表中选择目标 **HWND**
2. 输入自然语言任务（例如：「打开记事本并输入 hello」）
3. 点击 **开始**

运行时循环：

```text
截图 → Vision 决策（多步计划）→ ActionValidator → ActionExecutor
     → WindowsInputExecutor → 本地 Frame Diff 校验
```

界面会展示当前状态、执行步骤、最近一次校验通过的 Action，以及模型给出的 `decision_summary`。

### 常用运行参数

| 环境变量 | 默认 | 说明 |
|----------|------|------|
| `WGA_AGENT_MAX_PLAN_ACTIONS` | `5` | 单轮最多连续动作数 |
| `WGA_AGENT_ACTION_DELAY_MS` | `500` | 动作后等待再截图（避免刷新未完成误判） |
| `WGA_AGENT_FRAME_DIFF_THRESHOLD` | `0.005` | Frame Diff 变化阈值 |

`click` / `type` 的低分差异仅作为下一轮软证据，不会单独打断多步计划；`scroll` 在无明显变化时会中止剩余步骤。

## 动作空间

```text
click, double_click, right_click, type, hotkey,
scroll, wait, finish, fail
```

模型输出为多步计划，经 `parse_decision()` 校验；执行前由 `ActionValidator` 检查目标窗口、坐标、等待时间与热键白名单。

## 调试与测试

仅请求模型并打印校验后的 `AgentDecision`（不执行 GUI 动作）：

```powershell
.\.venv\Scripts\python.exe scripts\debug_qwen.py
```

完整测试（Windows）：

```powershell
.\.venv\Scripts\python.exe -m pytest
```

开发机无 Windows 输入 API 时可跳过相关用例：

```bash
pytest tests/ -q --ignore=tests/test_input_executor.py
```

开发进度见 [PLAN.md](PLAN.md)。

## 已知行为

- Hotkey 在 Schema 层统一为「一项一个按键」；`CTRL+A` 简写会安全拆分
- 目标窗口最小化时暂停周期截图，恢复后可立即截图继续
- `TextInputHost.exe` 不会出现在候选窗口列表；全黑帧在调用模型前会被拒绝
- Frame Diff 已接入 Runtime 的 VERIFY 阶段

## 当前限制

- UI Automation、被动变化监控、独立 Verifier LLM 尚未实现
- Agent 会发出**真实**鼠标键盘输入，请先在记事本、计算器等安全窗口中验证

## 许可证

仅供学习与研究使用。请勿用于未经授权的自动化或恶意操作。
