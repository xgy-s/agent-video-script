# 01 需求文档 — 短视频脚本 Agent

## 用户与目标

| 项 | 内容 |
|---|---|
| 用户 | 短视频创作者 / 内容运营 |
| 痛点 | 脚本中的产品卖点容易凭印象乱写；时长靠感觉，常超平台限制 |
| 目标 | 生成**有事实依据、满足时长限制**的可编辑脚本草稿 |
| 非目标 | 真实发布、视频剪辑、多 Agent 协作、生产级 Runtime |

## 输入与输出

**输入**（CLI 参数）：主题 topic、受众 audience、平台 platform（douyin/kuaishou/xiaohongshu）、目标时长 duration（秒）、风格 style。

**输出**（JSON）：标题、分镜列表（画面 visual / 旁白 narration / 素材来源 material_ids）、预计总时长 total_seconds、素材来源 ID 列表、风险说明 risk_notes、任务状态 status。

## 任务状态机

| status | 含义 | 触发动作（均由模型选择） |
|---|---|---|
| `completed` | 检查全部通过，草稿提交 | `submit_script` |
| `needs_info` | 缺关键输入（topic 或 duration） | `request_info` |
| `unfinished` | 无法满足约束，明确声明原因 | `declare_unfinished`；或达到步数/调用上限 |
| `failed` | 工具重试后仍失败 | `report_failure` |

## 可用工具（本地确定性函数）

1. `search_materials(query)` — 检索合成产品素材（`data/materials.json`，P01~P05）
2. `estimate_duration(script)` — 估算脚本总时长，对照目标时长
3. `check_rules(script)` — 品牌禁用词 / 引用真实性 / 效果型结论溯源 / 平台时长上限（`data/rules.json`）

## 成功标准（验收点映射）

| # | 验收点 | 成功表现 | 验证材料 |
|---|---|---|---|
| A1 | 正常生成 | 检索→估算达标→检查通过→提交，事实均标注素材 ID | examples/case1_normal.json、case1_normal_real.json |
| A2 | 缺关键信息 | 返回 needs_info 并列出缺失字段 | examples/case2_missing_info.json |
| A3 | 无素材 | 改写查询重试一次，仍为空则 unfinished(no_material)，不编造内容 | examples/case3_no_material.json |
| A4 | 工具失败 | 重试一次仍失败则 failed，如实记录 ERROR，不虚报成功 | examples/case4_tool_failure.json |
| A5 | 超时长 | 压缩修正后重新估算直至达标；无法满足则明确声明失败原因 | examples/case5_over_duration.json、case5_over_duration_real.json、case6_real_revise_loop.json |
| A6 | 上限保护 | 达到步数/调用上限返回 unfinished(step_limit / tool_call_limit) | examples/case8_real_step_limit.json、tests/test_agent_mock.py::TestStepLimit |
| A7 | 规则违规修正（加分） | 检查判违规 → 模型改写 → 复检通过才提交 | examples/case7_real_rule_violation_fix.json |

## 关键红线

- 脚本事实必须来自检索素材并标注 ID；禁止编造数据型结论（如"效率提升 80%"）。
- 只产出脚本草稿，不涉及真实发布。
- 仓库不包含真实密钥（`.env` 已 gitignore，仅提交 `.env.example`）。
