"""ReAct 主循环：模型选择动作 → 执行工具 → 观察结果 → 模型调整下一步或结束。

骨架只负责：维护消息历史、执行工具、回传结果、限步/限调用。
每个动作（含何时结束、以什么状态结束）全部由模型当步 function call 决定。
"""
from __future__ import annotations

import json

from .tools import ToolError, execute_tool, estimate_duration, load_materials, load_rules
from .trace import TraceRecorder

DEFAULT_MAX_STEPS = 12
DEFAULT_MAX_TOOL_CALLS = 15

# 终止类动作：模型调用即结束任务（动作本身也是模型选择的）
TERMINAL_ACTIONS = {
    "submit_script": "completed",
    "declare_unfinished": "unfinished",
    "report_failure": "failed",
    "request_info": "needs_info",
}

SYSTEM_PROMPT = """你是短视频脚本创作 Agent。根据用户给定的主题、受众、平台、目标时长与风格，
通过调用工具完成"有事实依据、时长合规"的脚本草稿。

可用动作（每步选择一个）：
1. search_materials(query) —— 检索产品素材，脚本中的事实只能来自检索结果
2. estimate_duration(script) —— 估算脚本总时长，对照目标时长
3. check_rules(script) —— 品牌/事实/平台规则检查
4. submit_script(script, risk_notes) —— 检查全部通过后提交，任务完成
5. declare_unfinished(reason, detail) —— 无法满足时明确声明未完成及原因
6. report_failure(reason) —— 工具重试仍失败时报告失败
7. request_info(missing_fields) —— 仅当 topic 或 duration 缺失时使用；其余输入（受众/平台/风格）为空属正常，品牌规则由 check_rules 工具内置，无需询问用户

硬性约束：
- 脚本中每条产品事实必须来自已检索素材，并在分镜 material_ids 标注来源；禁止编造数据（如"效率提升80%"）。
- 总时长不得超过目标时长；超出时应压缩脚本后重新估算，再决定提交或声明无法满足。
- 规则检查未通过时，修正后重新检查，不得直接提交。
- 工具报错时可换参数重试一次；仍失败则 report_failure，不得假装成功。
- 同一工具用相同参数重复调用不会得到新结果，不要重复调用；仅在参数确实变化（改写查询/压缩脚本）时重试。
- 检索为空时可改写查询重试一次；仍为空则 declare_unfinished(reason="no_material")。
- 只产出脚本草稿，不涉及真实发布。

script 结构：{"title": str, "shots": [{"idx": int, "visual": str, "narration": str, "material_ids": [str]}]}
"""


def _script_arg(name: str, required: bool = True) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": "对给定脚本执行操作",
            "parameters": {
                "type": "object",
                "properties": {
                    "script": {
                        "type": "object",
                        "description": "脚本草稿",
                        "properties": {
                            "title": {"type": "string"},
                            "shots": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "idx": {"type": "integer"},
                                        "visual": {"type": "string"},
                                        "narration": {"type": "string"},
                                        "material_ids": {"type": "array", "items": {"type": "string"}},
                                    },
                                    "required": ["idx", "visual", "narration", "material_ids"],
                                },
                            },
                        },
                        "required": ["title", "shots"],
                    }
                },
                "required": ["script"] if required else [],
            },
        },
    }


TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "search_materials",
            "description": "按关键词检索产品素材，返回素材ID与事实列表",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "检索关键词"}},
                "required": ["query"],
            },
        },
    },
    _script_arg("estimate_duration"),
    _script_arg("check_rules"),
    {
        "type": "function",
        "function": {
            "name": "submit_script",
            "description": "全部检查通过后提交最终脚本，任务完成",
            "parameters": {
                "type": "object",
                "properties": {
                    "script": {"type": "object"},
                    "risk_notes": {"type": "string"},
                },
                "required": ["script", "risk_notes"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "declare_unfinished",
            "description": "明确声明任务未完成及原因",
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {"type": "string"},
                    "detail": {"type": "string"},
                },
                "required": ["reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "report_failure",
            "description": "工具重试后仍失败，报告任务失败",
            "parameters": {
                "type": "object",
                "properties": {"reason": {"type": "string"}},
                "required": ["reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "request_info",
            "description": "缺少关键输入时请求用户补充",
            "parameters": {
                "type": "object",
                "properties": {
                    "missing_fields": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["missing_fields"],
            },
        },
    },
]


def _openai_tool_call(call_id: int, name: str, arguments: dict) -> dict:
    return {
        "id": f"call_{call_id}",
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)},
    }


def _build_output(status: str, action: str, args: dict, ctx: dict) -> dict:
    if action == "submit_script":
        script = args.get("script", {})
        est = estimate_duration(script, ctx.get("target_seconds"))
        check = ctx.get("last_check") or {}

        # 分镜级对应表：分镜 → 时长 → 素材来源 → 事实原文（审核可逐条核对）
        facts_map = ctx.get("material_facts", {})
        shots = []
        for shot, per in zip(script.get("shots", []), est["per_shot"]):
            mids = shot.get("material_ids", [])
            shots.append({
                "idx": shot.get("idx"),
                "visual": shot.get("visual"),
                "narration": shot.get("narration"),
                "material_ids": mids,
                "seconds": per["seconds"],
                "narration_chars": per["narration_chars"],
                "facts_from_materials": [f for mid in mids for f in facts_map.get(mid, [])],
            })

        return {
            "status": status,
            "title": script.get("title"),
            "shots": shots,
            "per_shot_seconds": {s["idx"]: s["seconds"] for s in shots},
            "total_seconds": est["total_seconds"],
            "target_seconds": ctx.get("target_seconds"),
            "remaining_seconds": est.get("remaining_seconds"),
            "material_ids": ctx.get("retrieved_ids", []),
            "checks": {
                "duration": {
                    "total_seconds": est["total_seconds"],
                    "target_seconds": ctx.get("target_seconds"),
                    "within_limit": est.get("within_limit"),
                    "per_shot": est["per_shot"],
                },
                "rules": {
                    "passed": check.get("passed"),
                    "violations": check.get("violations", []),
                    "violation_details": check.get("violation_details", []),
                    "checked_shots": check.get("checked_shots"),
                },
            },
            "risk_notes": args.get("risk_notes", ""),
            "note": "脚本草稿，未发布",
        }
    if action == "request_info":
        return {"status": status, "missing_fields": args.get("missing_fields", [])}
    return {"status": status, "reason": args.get("reason"), "detail": args.get("detail", "")}


def run_agent(
    task: dict,
    client,
    *,
    max_steps: int = DEFAULT_MAX_STEPS,
    max_tool_calls: int = DEFAULT_MAX_TOOL_CALLS,
    fail_inject: set[str] | None = None,
) -> dict:
    """执行 ReAct 循环，返回 {"status", "output", "trace"}。"""
    materials = load_materials()
    ctx = {
        "materials": materials,
        "rules": load_rules(),
        "material_facts": {m["id"]: m["facts"] for m in materials},
        "retrieved_ids": [],
        "platform": task.get("platform"),
        "target_seconds": task.get("duration"),
        "last_estimate": None,
        "last_check": None,
    }
    rec = TraceRecorder(task)
    rec.set_limits(max_steps, max_tool_calls)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "任务输入：" + json.dumps(task, ensure_ascii=False)},
    ]

    tool_calls_used = 0
    status, output = None, None

    for step in range(1, max_steps + 1):
        resp = client.complete(messages, TOOL_SCHEMAS)
        content, calls = resp["content"], resp["tool_calls"]

        if not calls:
            # 模型未选择任何动作：提示其必须调用工具，计一步
            messages.append({"role": "assistant", "content": content})
            messages.append({"role": "user", "content": "请通过工具调用继续：检索/估算/检查/提交/终止。"})
            continue

        messages.append({
            "role": "assistant",
            "content": content,
            "tool_calls": [_openai_tool_call(tool_calls_used + i + 1, c["name"], c["arguments"])
                           for i, c in enumerate(calls)],
        })

        for call in calls:
            name, args = call["name"], call["arguments"]
            tool_calls_used += 1

            if tool_calls_used > max_tool_calls:
                status, output = "unfinished", {
                    "reason": "tool_call_limit",
                    "detail": f"达到工具调用上限 {max_tool_calls}，任务未完成",
                }
                rec.record(step, name, args, error=output["detail"], rationale=content)
                break

            if name in TERMINAL_ACTIONS:
                status = TERMINAL_ACTIONS[name]
                output = _build_output(status, name, args, ctx)
                rec.record(step, name, args,
                           result={"script": args.get("script", {})} if name == "submit_script" else args,
                           rationale=content)
                break

            try:
                result = execute_tool(name, args, ctx=ctx, fail_inject=fail_inject)
                if name == "estimate_duration":
                    ctx["last_estimate"] = result
                elif name == "check_rules":
                    ctx["last_check"] = result
                rec.record(step, name, args, result=result, rationale=content)
                payload = json.dumps(result, ensure_ascii=False)
            except ToolError as e:
                rec.record(step, name, args, error=str(e), rationale=content)
                payload = json.dumps({"error": str(e)}, ensure_ascii=False)

            messages.append({
                "role": "tool",
                "tool_call_id": f"call_{tool_calls_used}",
                "name": name,
                "content": payload,
            })

        if status:
            break

    if not status:
        status = "unfinished"
        output = {"reason": "step_limit",
                  "detail": f"达到最大步数 {max_steps}，任务未完成"}

    rec.finish(status, output)
    return {"status": status, "output": output, "trace": rec.data}
