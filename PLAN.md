# 项目规划（PLAN）— 短视频脚本 Agent

> 工作文档，非交付必需；交付文档以 docs/01~05 为准。
> 技术栈：Python 3.10+ · 千问（DashScope，OpenAI 兼容模式 + function calling）· pytest · CLI

## 1. 目标与验收映射

交付一个可运行的 CLI Agent，满足题 4 全部验收点：

| # | 验收点 | 对应测试 | 对应 Trace（examples/） |
|---|---|---|---|
| A1 | 正常生成 | test_normal_flow | case1_normal.json / case1_normal_real.json |
| A2 | 缺关键信息 | test_missing_info | case2_missing_info.json |
| A3 | 无素材 | test_no_material | case3_no_material.json |
| A4 | 工具失败 | test_tool_failure | case4_tool_failure.json |
| A5 | 超时长修正 | test_over_duration_revise | case5_over_duration.json / case5_over_duration_real.json / case6_real_revise_loop.json |
| A6 | 上限保护 | test_step_limit | case8_real_step_limit.json |
| A7 | 规则违规修正（加分） | test_banned_word / test_shot_level_fact_traceability | case7_real_rule_violation_fix.json |

硬性要求核对：≥1 个真实 ReAct 循环（function calling 驱动）、≥2 条不同执行路径 Trace、步数上限 + 明确未完成状态、≥3 组验证材料覆盖正常/信息不足/工具失败。

## 2. 架构与调用流程

```
用户输入(主题/受众/平台/时长/风格)
      │
      ▼
┌─────────────┐   选择动作(function call)   ┌──────────────┐
│  Qwen 模型   │ ─────────────────────────▶ │  tools.py     │
│ (ReAct 决策) │ ◀───────────────────────── │ 检索/估算/检查 │
└─────────────┘        观察结果(摘要)        └──────────────┘
      │ 循环 ≤ MAX_STEPS，模型每步决定：继续调工具 / 修正脚本 / 结束
      ▼
结构化输出：标题/分镜/旁白/总时长/素材ID/风险/状态 + Trace 落盘 examples/
```

- 模型每轮通过 function calling 返回动作，**不写死分支**；框架只负责执行工具、回传结果、计数限步。
- 达到 `MAX_STEPS=12` 或 `MAX_TOOL_CALLS=15` → 输出 `status=unfinished` 与原因。

## 3. 模块划分（src/）

| 文件 | 职责 | 关键设计 |
|---|---|---|
| `cli.py` | 参数解析、编排、打印与 Trace 落盘 | `--mock` 切换离线模型；`--case` 复现示例 |
| `agent.py` | ReAct 主循环 | 消息历史、步数/调用计数、终止判定、unfinished 状态 |
| `model.py` | 模型层 | `QwenClient`（dashscope OpenAI 兼容，model 默认 `qwen-plus`）；`MockModelClient`（离线，**仅验证流程**，README 已标边界） |
| `tools.py` | 业务工具（本地函数） | `search_materials` / `estimate_duration` / `check_rules`；支持测试注入失败 |
| `trace.py` | 运行记录 | JSON：步骤、工具参数、返回摘要、后续动作、决策依据 |

## 4. 工具与数据设计

- `search_materials(query)`：在 `data/materials.json` 做关键词匹配（合成素材，如 P01 "支持字幕"）。
- `estimate_duration(script)`：**确定性启发式** = 旁白字数 ÷ 语速(4.5 字/秒) + 每分镜 1.5s 缓冲 → 可复现、可断言。
- `check_rules(script, materials)`：对照 `data/rules.json`（品牌禁用词、必须引用素材 ID、时长上限）返回违规列表。
- 数据文件：`data/materials.json`（5~8 条合成素材）、`data/rules.json`（品牌/平台规则）。

## 5. ReAct 决策点（模型真实选择的动作）

1. 检索无结果 → 模型决定**改写查询再检索** 或 **请求补充信息** 或 **停止**。
2. 时长估算超限 → 模型决定**压缩脚本后重新估算**（可多次）或**声明无法满足**。
3. 规则检查违规 → 模型决定**修订并复检** 或 **标记风险结束**。
4. 工具异常 → 模型决定**换参数重试一次** 或 **终止并报告工具失败**。

预设骨架仅负责循环与限步；以上分支全部由模型当步输出决定（Trace 中记录决策依据）。

## 6. 测试计划（tests/）

- 单元：估算器数值、规则检查命中、检索匹配、Trace 结构。
- 集成（Mock 模型驱动全流程，确定性）：A1~A6 六条用例；A5 断言出现"估算→超限→压缩→再估算→通过"的轨迹；A4 注入 `search_materials` 抛错，断言状态为 failed 且不误报成功。
- 真实模型冒烟（可选，`--real`，需 Key）：跑 A1/A5 两条，Trace 存 examples/ 并在 03 文档标注。

## 7. examples/ 与 docs/ 产出

- examples/：5 个 case 各含 input、output、trace（其中 case1 正常 + case5 修正循环即两条不同执行路径）。
- docs/01~05 按规范填写；03-evaluation 引用 examples/ 具体文件；04-ai-usage 如实记录 AI 生成范围与个人修改。

## 8. 里程碑（总预算 ~3h）

| 阶段 | 内容 | 产出 |
|---|---|---|
| M1 | 骨架 + 数据 + 工具 + 估算器 | tools/data + 单元测试 |
| M2 | Qwen 接入 + ReAct 循环 + 限步 | agent/model + case1 跑通 |
| M3 | Mock 模型 + 6 条集成测试 | tests 全绿 |
| M4 | 5 个 case Trace + 真实模型冒烟 | examples/ |
| M5 | docs/01~05 + README 校对 | 交付件齐 |

## 9. 风险与对策

- **模型决策不稳定** → system prompt 明确动作清单与终止条件；temperature=0；Mock 兜底保证 CI 可重复。
- **估算口径被质疑** → 在 docs/02 写明启发式公式与假设，测试固定语速常量。
- **事实编造（关键缺陷）** → prompt 约束 + check_rules 校验"脚本事实 ⊆ 已检索素材"，违规必须修正。
- **超时** → M3 完成即为核心链路可用；M4 真实冒烟可裁剪为 1 条。

## 10. 待确认

- [ ] DashScope API Key 是否已具备（决定 M4 真实模型冒烟范围）
- [ ] 默认模型 `qwen-plus` 是否可接受（qwen-turbo 更快更省）
