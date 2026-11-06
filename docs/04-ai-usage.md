# 04 AI 使用记录

## 使用的 AI 工具

| 工具 | 用途 |
|---|---|
| Trae（Kimi-K3 模型） | 选题分析、项目规划、全部代码与文档的生成、测试修复、真实模型联调 |
| 千问 qwen-plus（DashScope） | 被测对象：作为 Agent 的决策模型运行 ReAct 循环 |

## AI 生成的内容（如实范围）

本项目在 AI 辅助下完成，AI 生成范围包括：

- `README.md`、`PLAN.md`、`docs/01~05` 全部文档初稿；
- `src/` 全部代码（cli / agent / model / tools / trace / web）；
- `tests/` 全部测试；
- `data/materials.json`、`data/rules.json` 合成数据；
- examples/ 中 Mock 轨迹由 AI 编写的程序运行产生；`*_real.json` 为真实 qwen 模型实际运行的输出。

## 个人贡献与验证

| 事项 | 说明 |
|---|---|
| 选题决策 | 本人在四道题中选择题 4（AI 给出对比分析，本人拍板） |
| 技术选型 | 本人指定 Python + 千问 API，确认不用重型框架、原生实现 ReAct |
| 提供凭证 | DashScope API Key 由本人提供，仅写入本地 `.env`（已 gitignore，未入库） |
| 运行验证 | `pytest` 45 passed、Mock 5 个 case、真实模型 5 条 Trace（case1/5/6/7/8）均为本机实际运行结果 |
| 失败修复确认 | qwen JSON 截断、request_info 误判、Mock 状态解析三处问题均由实际运行/测试暴露后修复，修复过程见 docs/03 |

## 验证方式（可复现）

```bash
pip install -r requirements.txt
pytest tests/ -v                                              # 45 passed
python -m src.cli --mock --topic "便携榨汁杯" --duration 60    # 离线冒烟
python -m src.cli --topic "便携榨汁杯" --duration 60           # 真实模型（需 .env 配 Key）
```

## 说明

- AI 生成内容均经过实际运行验证，未通过验证的部分（如初版 Mock 解析、初版 prompt）已修正并在 docs/03 记录。
- 未使用 AI 伪造任何运行结果：examples/ 全部 Trace 由程序真实执行生成，含时间戳可核对。
