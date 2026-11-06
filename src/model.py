"""模型层：Qwen（DashScope OpenAI 兼容 + function calling）与离线 Mock。

边界说明：
- QwenClient 是真实模型，动作（调用哪个工具/是否结束）由模型当步输出决定。
- MockModelClient 是离线替身，用确定性脚本模拟同样的 function-calling 轨迹，
  仅用于无网/无 Key 时验证流程与测试可重复，不证明真实模型决策效果。
两个客户端实现同一接口：complete(messages, tool_schemas) ->
{"content": str, "tool_calls": [{"name": str, "arguments": dict}]}
"""
from __future__ import annotations

import json
import os


# ---------------------------------------------------------------- 真实模型

class QwenClient:
    def __init__(self, api_key: str | None = None, model: str | None = None):
        from openai import OpenAI  # 延迟导入，Mock 模式无需该依赖运行

        self.model = model or os.getenv("QWEN_MODEL", "qwen-plus")
        self._client = OpenAI(
            api_key=api_key or os.getenv("DASHSCOPE_API_KEY"),
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        )

    def complete(self, messages: list[dict], tool_schemas: list[dict]) -> dict:
        # qwen 偶发输出非法 JSON 参数：先宽松解析，仍失败则带提示重试，最多 3 次
        local = list(messages)
        last_err: Exception | None = None
        for _ in range(3):
            resp = self._client.chat.completions.create(
                model=self.model,
                messages=local,
                tools=tool_schemas,
                temperature=0,
                max_tokens=4096,
            )
            msg = resp.choices[0].message
            try:
                tool_calls = [
                    {"name": tc.function.name,
                     "arguments": _parse_arguments(tc.function.arguments)}
                    for tc in (msg.tool_calls or [])
                ]
                return {"content": msg.content or "", "tool_calls": tool_calls}
            except json.JSONDecodeError as e:
                last_err = e
                local = local + [
                    {"role": "assistant", "content": msg.content or ""},
                    {"role": "user",
                     "content": "上一次工具调用的参数不是合法 JSON，请重新调用工具，"
                                "arguments 必须是严格合法的 JSON 字符串。"},
                ]
        raise RuntimeError(f"模型连续返回非法 JSON 参数：{last_err}")


def _parse_arguments(raw: str | None) -> dict:
    """容错解析 function call 参数。

    qwen 偶发问题与对策：
    1. 字符串内含换行等控制字符 → strict=False；
    2. 输出被截断（缺尾部 `}`/`]`）→ 补全未闭合括号后再解析；
    两级容错都失败则抛 JSONDecodeError，由 complete() 提示模型重试。
    """
    text = (raw or "{}").strip().lstrip("﻿")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    try:
        return json.loads(text, strict=False)
    except json.JSONDecodeError:
        return json.loads(_close_truncated_json(text), strict=False)


def _close_truncated_json(text: str) -> str:
    """为被截断的 JSON 补全未闭合的字符串与括号。"""
    stack: list[str] = []
    in_string = False
    escaped = False
    for ch in text:
        if escaped:
            escaped = False
            continue
        if ch == "\\":
            escaped = True
        elif ch == '"':
            in_string = not in_string
        elif in_string:
            continue
        elif ch in "{[":
            stack.append(ch)
        elif ch in "}]":
            if stack:
                stack.pop()
    repaired = text
    if in_string:
        repaired += '"'
    for opener in reversed(stack):
        repaired += "}" if opener == "{" else "]"
    return repaired


# ---------------------------------------------------------------- 离线 Mock

class MockModelClient:
    """确定性策略替身。仅在 --mock 时使用。

    策略（与真实模型相同的 function-calling 轨迹）：
    检索 → (空结果则改写查询重试一次) → 起草完整脚本 → 估算
    → (超限则压缩后重新估算) → 规则检查 → 提交；
    工具报错重试一次仍失败 → report_failure；缺关键信息 → request_info。
    """

    def __init__(self, task: dict):
        self.task = task

    # -- 从消息历史还原状态 --
    def _state(self, messages: list[dict]) -> dict:
        st = {"searches": 0, "last_hits": None, "estimates": 0, "last_within": None,
              "checked": False, "failures": [], "materials": []}
        for m in messages:
            if m.get("role") == "assistant":
                for tc in m.get("tool_calls", []):
                    # OpenAI 格式：{"type": "function", "function": {"name": ..., ...}}
                    name = tc.get("function", {}).get("name", tc.get("name"))
                    if name == "search_materials":
                        st["searches"] += 1
                    elif name == "estimate_duration":
                        st["estimates"] += 1
                    elif name == "check_rules":
                        st["checked"] = True
            elif m.get("role") == "tool":
                try:
                    payload = json.loads(m["content"])
                except (json.JSONDecodeError, TypeError):
                    payload = {"error": m["content"]}
                if "error" in payload:
                    # 工具失败优先记录，不污染检索/估算结果状态
                    st["failures"].append(m["name"])
                elif m["name"] == "search_materials":
                    st["last_hits"] = payload.get("hit_count", 0)
                    st["materials"] = payload.get("hits", [])
                elif m["name"] == "estimate_duration":
                    st["last_within"] = payload.get("within_limit")
        return st

    # -- 脚本起草/压缩（离线模板，仅验证流程）--
    def _draft(self, long: bool) -> dict:
        facts = [f for h in self._hits for f in h["facts"]]
        mid = self._hits[0]["id"]
        f1 = facts[0] if facts else "卖点待补充"
        f2 = facts[1] if len(facts) > 1 else f1
        if long:
            n2 = f"先看硬参数：{f1}，通勤、出差、健身房随手就能用，早上多睡十分钟也来得及做一杯"
            n3 = f"再看使用体验：{f2}，操作零门槛，老人孩子都能上手，清洗也不费劲"
        else:
            n2 = f1
            n3 = f2
        return {
            "title": f"通勤党狂喜：{self._hits[0]['product']}实测",
            "shots": [
                {"idx": 1, "visual": "特写：产品从通勤包取出", "narration": "通勤路上也能喝到鲜榨果汁？", "material_ids": []},
                {"idx": 2, "visual": "参数字幕+实测画面", "narration": n2, "material_ids": [mid]},
                {"idx": 3, "visual": "使用过程演示", "narration": n3, "material_ids": [mid]},
                {"idx": 4, "visual": "产品全家福+关注引导", "narration": "喜欢点关注，评论区见", "material_ids": []},
            ],
        }

    def complete(self, messages: list[dict], tool_schemas: list[dict]) -> dict:
        task = self.task
        # 缺关键信息：缺主题或目标时长 → 请求补充（验收 A2）
        if not task.get("topic") or not task.get("duration"):
            missing = [k for k in ("topic", "duration") if not task.get(k)]
            return self._call("request_info", {"missing_fields": missing},
                              f"缺少关键信息：{missing}，请补充后再生成")

        st = self._state(messages)

        # 工具失败：同一工具已失败过一次 → 报告失败（验收 A4）
        if st["failures"] and st["failures"][-1] in st["failures"][:-1]:
            return self._call("report_failure",
                              {"reason": f"工具 {st['failures'][-1]} 重试后仍失败"},
                              "工具重试后仍失败，终止任务")

        # 阶段 1：检索
        if st["searches"] == 0:
            return self._call("search_materials", {"query": task["topic"]},
                              "先检索与主题相关的素材")
        if st["failures"] and st["failures"][-1] == "search_materials" and st["last_hits"] is None:
            return self._call("search_materials", {"query": task["topic"]},
                              "检索工具失败，换相同参数重试一次")

        # 阶段 2：空结果 → 改写查询重试一次；仍为空 → 未完成（验收 A3）
        if st["last_hits"] == 0:
            if st["searches"] == 1:
                simplified = task["topic"][:2]
                return self._call("search_materials", {"query": simplified},
                                  "首次检索为空，改写为更宽的关键词重试")
            return self._call("declare_unfinished",
                              {"reason": "no_material",
                               "detail": "改写查询后仍无可用素材，需运营补充素材库"},
                              "两次检索均无素材，声明未完成")

        self._hits = st["materials"]

        # 阶段 3：起草完整脚本并估算时长
        if st["estimates"] == 0:
            draft = self._draft(long=True)
            self._script = draft
            return self._call("estimate_duration",
                              {"script": draft},
                              "起草完整脚本，先估算是否满足目标时长")

        # 阶段 4：超限 → 压缩后重新估算（验收 A5：修正循环）
        if st["last_within"] is False:
            short = self._draft(long=False)
            self._script = short
            return self._call("estimate_duration",
                              {"script": short},
                              "上一版超出目标时长，压缩旁白后重新估算")

        # 阶段 5：规则检查
        if not st["checked"]:
            return self._call("check_rules", {"script": self._script},
                              "时长达标，提交前做品牌/事实规则检查")

        # 阶段 6：提交
        return self._call("submit_script",
                          {"script": self._script,
                           "risk_notes": "事实均引用素材原文；无效果型结论"},
                          "检查通过，提交最终脚本")

    @staticmethod
    def _call(name: str, arguments: dict, rationale: str) -> dict:
        return {"content": rationale, "tool_calls": [{"name": name, "arguments": arguments}]}
