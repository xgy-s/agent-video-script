# 短视频脚本 Agent（题 4）

小影校招 AI Agent 开发岗考核项目。帮助创作者生成**有事实依据、满足时长限制**的可编辑短视频脚本：输入主题、受众、平台、目标时长与风格，Agent 通过 ReAct 循环调用素材检索、时长估算、规则检查工具，输出标题、分镜、旁白/字幕、预计总时长、素材来源 ID、风险与任务状态。

## 核心特性

- **真实 ReAct 决策循环**：模型选择动作 → 执行工具 → 观察结果 → 模型调整下一步或结束。时长/规则检查不通过时由模型决定压缩修正、重新检索或明确失败，非固定分支。
- **事实可追溯**：脚本中每条产品事实必须引用素材来源 ID；无依据的结论性表述（如"效率提升 80%"）禁止生成。
- **执行上限保护**：设置最大步数/工具调用次数，达到上限返回明确的 `unfinished` 状态与原因。
- **离线可运行**：模型不可用时提供离线 Mock 入口（`--mock`），Mock 仅验证流程，不证明真实模型决策效果。

## 环境

- Python 3.10+
- 依赖见 [requirements.txt](requirements.txt)
- 环境变量见 [.env.example](.env.example)；使用离线 Mock 模式时**无需任何配置**

## 安装

```bash
pip install -r requirements.txt
cp .env.example .env   # 真实模型模式：填入你的模型 API Key；Mock 模式可跳过
```

## 运行（CLI）

真实模型模式：

```bash
python -m src.cli --topic "便携榨汁杯" --audience "上班族" --platform "douyin" --duration 30 --style "活泼" --out examples/my_trace.json
```

离线 Mock 模式（无网络、无 Key，验证完整流程）：

```bash
python -m src.cli --mock --topic "便携榨汁杯" --audience "上班族" --platform "douyin" --duration 30 --style "活泼" --out examples/my_trace.json
```

常用参数：`--mock` 离线模式；`--out <path>` 落盘 Trace（步骤、工具参数、返回摘要、后续动作、决策依据）；`--fail-inject <工具名>` 注入工具失败（演示 A4 场景）；`--max-steps / --max-tool-calls` 调整执行上限。退出码：`completed=0`，其余状态=1。

## 运行（Web 界面，可选）

```bash
python -m src.web            # 打开 http://127.0.0.1:8000
```

浏览器表单提交主题/时长/平台等参数，调用与 CLI 相同的 `run_agent`，页面展示任务状态、分镜脚本与完整 Trace（含每步决策依据）。支持勾选"离线 Mock"与"注入检索工具失败"演示不同路径。仅标准库实现，不新增依赖。

## 测试

```bash
pytest tests/ -v
```

## 项目结构

```
README.md            # 本文件：环境、安装、运行、评审入口
src/                 # 项目代码与模型/工具接入
  cli.py             # CLI 入口（运行方式：CLI）
  agent.py           # ReAct 主循环（含步数上限与未完成状态）
  tools.py           # 素材检索 / 时长估算 / 规则检查（本地函数）
  model.py           # 模型接入 + 离线 Mock 入口（边界已标明）
tests/               # 可执行测试（覆盖全部验收点）
examples/            # 输入、实际输出、Trace（正常/信息不足/工具失败等场景）
data/                # 合成素材与品牌规则
docs/
  01-requirements.md # 用户、目标、范围和成功标准
  02-solution.md     # 调用流程、动态决策、技术取舍
  03-evaluation.md   # 测试预期、实际结果、失败和限制
  04-ai-usage.md     # AI 辅助内容、个人修改及验证
  05-retrospective.md# 最难问题、学习收获、下一步
requirements.txt
.env.example
```

## 验收点覆盖

| 验收点 | 验证材料 |
|---|---|
| 正常生成 | [examples/case1_normal.json](examples/case1_normal.json)、真实模型 [examples/case1_normal_real.json](examples/case1_normal_real.json) |
| 缺关键信息 | [examples/case2_missing_info.json](examples/case2_missing_info.json) |
| 无素材 | [examples/case3_no_material.json](examples/case3_no_material.json) |
| 工具失败 | [examples/case4_tool_failure.json](examples/case4_tool_failure.json) |
| 超时长修正 | [examples/case5_over_duration.json](examples/case5_over_duration.json)、真实模型 [case5_over_duration_real.json](examples/case5_over_duration_real.json)（47.9→29.5s）、[case6_real_revise_loop.json](examples/case6_real_revise_loop.json)（37.8→18.5s） |
| 规则违规修正 | 真实模型 [examples/case7_real_rule_violation_fix.json](examples/case7_real_rule_violation_fix.json)（禁用词被判违规→改写→复检通过） |
| 步数上限未完成 | [examples/case8_real_step_limit.json](examples/case8_real_step_limit.json) |

## 输出结构（可直接核对）

提交结果按分镜逐一给出：`idx / visual / narration / material_ids / seconds / facts_from_materials`，
并附 `per_shot_seconds`、`checks.duration`（含 `within_limit` 与逐镜明细）、`checks.rules`（含 `violation_details`）。
`per_shot_seconds` 之和等于 `total_seconds`，评审可逐镜核对"画面—旁白—时长—素材—事实原文"。

评估细节见 [docs/03-evaluation.md](docs/03-evaluation.md)。

## 评审入口

1. 需求与设计取舍：[docs/01-requirements.md](docs/01-requirements.md)、[docs/02-solution.md](docs/02-solution.md)
2. 运行记录（≥2 条不同执行路径，体现模型按工具结果调整动作）：[examples/](examples/)
3. 测试与效果：[docs/03-evaluation.md](docs/03-evaluation.md)、`pytest tests/ -v`
4. AI 使用与复盘：[docs/04-ai-usage.md](docs/04-ai-usage.md)、[docs/05-retrospective.md](docs/05-retrospective.md)

## 已知限制

- 素材库与品牌规则为合成数据（`data/`），不接真实检索系统。
- 时长估算为本地启发式（按字数/语速），非真实 TTS 计时；估算口径在 docs/02 中说明。
- 仅生成脚本草稿，不接真实发布流程。
- Mock 模式仅证明流程连通，真实模型决策效果以真实模型运行记录为准。
