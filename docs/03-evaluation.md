# 03 评估文档 — 测试预期、实际结果、失败和限制

## 自动化测试

命令：`pytest tests/ -v`（项目根目录）

**实际结果：45 passed**（本机 Python 3.12，0.14s）

| 文件 | 数量 | 覆盖 |
|---|---|---|
| tests/test_tools.py | 19 | 检索命中/为空、估算公式与 within_limit、禁用词、假引用、**分镜级事实溯源**、结构化违规明细、平台上限、失败注入 |
| tests/test_agent_mock.py | 16 | 验收点 A1~A6 全流程 + **分镜时长/检查结果逐一对应**断言 |
| tests/test_model_repair.py | 8 | qwen 非法 JSON 参数三级容错解析 |

## 验收点：预期 vs 实际

| # | 预期 | 实际结果 | 证据 |
|---|---|---|---|
| A1 正常生成 | completed，分镜级时长+素材 ID+检查结果齐全 | ✅ Mock 35.6s/4 分镜；真实 qwen 44.8s/7 分镜，逐镜给出 seconds 与 facts 原文 | [case1_normal.json](../examples/case1_normal.json)、[case1_normal_real.json](../examples/case1_normal_real.json) |
| A2 缺关键信息 | needs_info 并列出缺失字段 | ✅ 缺 duration → `missing_fields:["duration"]`，1 步结束 | [case2_missing_info.json](../examples/case2_missing_info.json) |
| A3 无素材 | 改写查询重试→仍空→unfinished(no_material) | ✅ 两次检索（原词→前两字改写）均 0 命中后声明未完成，未编造内容 | [case3_no_material.json](../examples/case3_no_material.json) |
| A4 工具失败 | 重试一次仍失败→failed，不虚报成功 | ✅ 两次 ERROR 如实入 Trace，第 3 步 report_failure | [case4_tool_failure.json](../examples/case4_tool_failure.json) |
| A5 超时长修正 | 压缩→重估→达标提交；或明确失败 | ✅ Mock：35.6s→21.1s；真实 qwen 30s：47.9→36.3→**29.5s** 两轮压缩后提交；真实 20s：37.8→28.2→26.1→22.4→**18.5s** 四轮压缩后提交 | [case5_over_duration.json](../examples/case5_over_duration.json)、[case5_over_duration_real.json](../examples/case5_over_duration_real.json)、[case6_real_revise_loop.json](../examples/case6_real_revise_loop.json) |
| A6 上限保护 | 达上限返回 unfinished 明确原因 | ✅ Mock：max_steps=2 → step_limit；真实模型 max_steps=4 → 压缩途中被截断，返回 `unfinished(step_limit)` | [case8_real_step_limit.json](../examples/case8_real_step_limit.json)、tests/test_agent_mock.py::TestStepLimit |

## 额外的真实决策证据（加分点）

[case7_real_rule_violation_fix.json](../examples/case7_real_rule_violation_fix.json) 是真实 qwen 在 10s 目标下的完整轨迹：

```
1 search_materials  命中 P01/P02/P05
2 estimate_duration 51.3s / 10s  → 超限
3 estimate_duration 18.4s        → 仍超限
4 estimate_duration 14.7s        → 仍超限
5 estimate_duration  8.3s        → 达标
6 check_rules       passed=False 违规：包含品牌禁用词「神器」
7 check_rules       passed=True  ← 模型改写标题后复检通过
8 submit_script     提交 3 分镜
```

这条同时证明了两类动态决策：**超时长压缩循环**与**规则违规修正复检**，均由模型根据工具返回值自行调整，代码中没有对应分支。

## 审核要点核对：分镜 ID、时长、检查结果逐一对应

`submit_script` 输出中的 `shots` 数组逐镜给出：

```json
{
  "idx": 2,
  "narration": "杯身 450ml，重量 380g，可放入通勤包侧袋",
  "material_ids": ["P01"],
  "seconds": 7.1,
  "facts_from_materials": ["杯身 450ml，重量 380g，可放入通勤包侧袋", "..."]
}
```

同时 `checks.duration.per_shot` 与 `checks.rules`（含 `violation_details` 的 `shot_idx`）随输出一并交付，`per_shot_seconds` 之和等于 `total_seconds`（tests/test_agent_mock.py::test_per_shot_seconds_correspond 断言）。评审可对每个分镜逐一核对“画面-旁白-时长-素材-事实原文”。

## 改变输入后动作是否调整（审核要点）

| 变量 | 变化 | 模型下一步动作 |
|---|---|---|
| 目标时长 | 60s → 30s → 20s → 10s | 60s 一次通过；30s 压缩 2 轮；20s 压缩 4 轮；10s 压缩 4 轮并触发规则修正 |
| 检索结果 | 命中 → 0 命中 | 改写查询重试，仍空则 declare_unfinished |
| 工具状态 | 正常 → 持续报错 | 重试一次 → report_failure |
| 规则结果 | 通过 → 禁用词违规 | 改写后重新 check_rules 直至通过 |

## 失败与问题记录（如实）

1. **qwen 返回截断 JSON**（开发期失败）：`check_rules` 参数缺末尾 `}`，`json.loads` 崩溃。修复为三级容错解析 + `max_tokens=4096`，补 8 个单测。
2. **模型误判缺信息**（开发期失败）：初版 prompt 下模型以缺 brand 为由 request_info。收紧 prompt（仅 topic/duration 可请求补充）修复。
3. **Mock 状态解析 bug**（测试暴露）：工具错误被当作“0 命中检索结果”，A4 走错分支。修复 `_state` 错误优先记录。
4. **事实溯源粒度粗**（本轮优化）：原实现用全局 facts 池，任何素材的事实都能给任意分镜作依据。已改为**分镜级**：分镜旁白中的效果型结论必须来自该分镜自己引用的素材，且违规明细带 `shot_idx`。
5. **同一脚本重复估算**（偶发，不阻塞）：极限时长下模型会对同一脚本重复估算。已在 prompt 增加约束，真实运行中仍偶见 1~2 次冗余。

## 已知限制

- 素材/规则为合成数据，检索是关键词包含匹配，无语义检索能力；真实场景应换向量检索。
- 时长估算为字数启发式（4.5 字/秒 + 1.5s/分镜），未做 TTS 实测校准，误差未量化。
- 效果型结论检测依赖正则，仅覆盖百分比/倍数/“提升 N”类；无数字夸大（如“遥遥领先”）由品牌禁用词部分覆盖，无法全覆。
- Mock 模式仅验证流程连通，不证明真实模型决策效果；真实效果以 `*_real.json` 为准。
- 真实模型行为受模型版本与 prompt 影响，非完全确定；已用 temperature=0 降低波动。
