# 02 方案文档 — 调用流程、动态决策、技术取舍

## 技术栈与版本

| 组件 | 选择 | 承担的职责 |
|---|---|---|
| 语言 | Python 3.10+ | 全部实现 |
| 模型 | 千问 qwen-plus（DashScope OpenAI 兼容端点，`openai` SDK ≥1.0，function calling，temperature=0） | ReAct 决策：每步选择调哪个工具 / 是否结束 |
| 框架 | **不用 LangGraph/ADK，原生实现** | 循环骨架仅 ~100 行，考核重点是决策链路而非框架；原生实现便于说明每一处取舍 |
| 测试 | pytest 7 | 单元 + 集成 |
| 运行方式 | CLI（`python -m src.cli`） | 题目三选一之 CLI |

## 调用流程（ReAct 主循环）

```
用户输入 ──▶ system prompt + 任务 JSON
              │
   ┌──────────▼───────────┐
   │ 模型输出 function call │◀────────────────────┐
   └──────────┬───────────┘                     │
              ▼                                  │
   src/agent.py：执行工具（src/tools.py）          │
              │                                  │
              ▼                                  │
   结果/错误作为 tool 消息回传 ──────────────────┘
   循环直到：模型调用终止类动作，或达到 MAX_STEPS=12 / MAX_TOOL_CALLS=15
```

- 骨架只负责：维护消息历史、执行工具、回传结果、计数限步、落盘 Trace。
- **每个动作（含何时结束、以什么状态结束）全部由模型当步 function call 决定**，代码中不存在"如果超时就压缩"之类的固定分支。

## 动态决策点（模型真实选择）

1. **检索为空** → 改写查询重试 / 请求补充 / 停止。实例：case3 中模型把 `"不存在的商品xyz"` 改写为前两字重试，仍空则 `declare_unfinished(no_material)`。
2. **时长超限** → 压缩脚本重新估算（可多轮）/ 声明无法满足。实例：
   - [case6_real_revise_loop.json](../examples/case6_real_revise_loop.json)：真实模型 20s 目标，37.8s → 28.2s → 26.1s → 22.4s → **18.5s** 四轮压缩后达标提交；
   - [case8_real_step_limit.json](../examples/case8_real_step_limit.json)：同一任务限制 4 步，压缩途中被截断，返回 `unfinished(step_limit)` 而非假装完成。
3. **规则违规** → 修正后复检。实例：[case7_real_rule_violation_fix.json](../examples/case7_real_rule_violation_fix.json)，真实模型标题含禁用词「神器」被 `check_rules` 判违规，模型改写后重新检查通过才提交。
4. **工具报错** → 换参数重试一次 / `report_failure`。实例：case4 注入检索故障，模型重试一次后报告失败，**没有**把失败步骤记为成功。
5. **缺关键信息** → `request_info`。实例：case2 缺 duration，直接请求补充而非猜测默认值。

## 关键设计取舍

### 时长估算口径（启发式，确定性）

```
每分镜时长 = 旁白字数 ÷ 4.5 字/秒 + 1.5s 画面缓冲
总时长 = 各分镜之和（保留 1 位小数）
```

- 取中文口播常见语速 4~5 字/秒的中值；1.5s 覆盖镜头切换与画面留白。
- 选启发式而非 TTS 实测：**确定性可复现**，测试可断言精确数值；代价是估算偏粗，已在 README 已知限制中声明。

### 规则检查（事实防编造的核心）

`check_rules` 做五类校验，任一不通过即返回违规列表（含结构化 `violation_details`，带 `code` 与 `shot_idx`）给模型修正：

1. 引用的素材 ID 必须 ∈ 本次检索结果（防引用不存在的来源）；
2. 品牌禁用词（`data/rules.json`：最好/第一/神器/100% 等）；
3. **分镜级效果型结论溯源**：某分镜旁白中的百分比/倍数/"提升 N"类表述，其数字必须出现在**该分镜自己引用的素材** facts 中；无引用素材的分镜出现效果型结论直接判违规。这比全局池更严格，防止"A 素材的事实被 B 分镜借用"；
4. 标题中的效果型结论按本次检索全局池校验；
5. 平台时长上限（抖音/快手 60s，小红书 90s）。

### 输出可审核性（分镜逐一对应）

提交输出的每个分镜同时携带：`idx`、`visual`、`narration`、`material_ids`、`seconds`（该镜估算时长）、`narration_chars`、`facts_from_materials`（引用素材的事实原文）。

`per_shot_seconds` 之和严格等于 `total_seconds`；`checks.duration.per_shot` 与 `checks.rules`（含违规明细）随输出一并交付。评审可逐镜核对"画面—旁白—时长—素材 ID—事实原文"，无需回翻 Trace。

### 终止类动作也建模为工具

`submit_script / declare_unfinished / report_failure / request_info` 都是 function tool。结束状态不是代码判断出来的，而是模型"调用"出来的——这让"模型决定何时以及如何结束"在 Trace 中可直接核对。

### 错误处理：失败是观察，不是异常

工具失败（含 `--fail-inject` 注入）以 `{"error": ...}` 作为 tool 消息回传，由模型决定重试或终止；骨架不自动重试（自动重试不算 ReAct 决策）。

### Qwen 工程适配（真实踩坑）

- qwen-plus 偶发返回**尾部截断的非法 JSON 参数**（真实案例：case1 冒烟时 `check_rules` 参数缺末尾 `}`）。对策：`_parse_arguments` 三级容错（标准解析 → strict=False 容忍控制字符 → 补全未闭合括号），仍失败则带提示重试最多 3 次；并显式 `max_tokens=4096` 降低截断概率。
- 初版 system prompt 未限定 `request_info` 适用范围，模型曾把"品牌规则"当作缺失信息来问；已在 prompt 中明确"仅 topic/duration 缺失才可请求补充"。

## 离线 Mock 边界

`MockModelClient` 用确定性策略走**同一条 function-calling 轨迹**（同样产出 tool_calls、同样经骨架执行真实工具），仅用于无网/无 Key 时验证流程与测试可重复。**Mock 只证明流程连通，真实模型决策效果以 examples/ 中 `*_real.json` 运行记录为准。**
