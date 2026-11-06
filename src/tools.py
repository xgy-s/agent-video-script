"""业务工具层：素材检索 / 时长估算 / 规则检查。

全部为本地确定性函数（考核允许 Mock 业务工具）；
支持失败注入（fail_inject），用于验收"工具失败"场景。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

# 时长估算口径（启发式，docs/02 中说明）：
#   每分镜时长 = 旁白字数 / CHARS_PER_SEC + SHOT_BUFFER_SEC
CHARS_PER_SEC = 4.5
SHOT_BUFFER_SEC = 1.5

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


class ToolError(Exception):
    """工具执行失败（含注入失败）。消息对模型可见。"""


def load_materials(data_dir: Path | None = None) -> list[dict]:
    path = (data_dir or DATA_DIR) / "materials.json"
    return json.loads(path.read_text(encoding="utf-8"))


def load_rules(data_dir: Path | None = None) -> dict:
    path = (data_dir or DATA_DIR) / "rules.json"
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- 素材检索

def search_materials(query: str, materials: list[dict]) -> list[dict]:
    """按关键词命中检索素材。query 命中 keyword 或 product 即返回该素材。"""
    q = query.strip().lower()
    hits = []
    for m in materials:
        haystacks = [m["product"].lower(), *[k.lower() for k in m["keywords"]]]
        if any(q and (q in h or h in q) for h in haystacks):
            hits.append({"id": m["id"], "product": m["product"], "facts": m["facts"]})
    return hits


# ---------------------------------------------------------------- 时长估算

def _shot_seconds(narration: str) -> float:
    return round(len(narration) / CHARS_PER_SEC + SHOT_BUFFER_SEC, 1)


def estimate_duration(script: dict, target_seconds: int | None = None) -> dict:
    """估算脚本总时长。返回每分镜明细与总时长；给 target 时附带是否超限。"""
    per_shot = []
    for shot in script.get("shots", []):
        per_shot.append({
            "idx": shot.get("idx"),
            "narration_chars": len(shot.get("narration", "")),
            "seconds": _shot_seconds(shot.get("narration", "")),
            "material_ids": shot.get("material_ids", []),
        })
    total = round(sum(s["seconds"] for s in per_shot), 1)
    result = {"total_seconds": total, "per_shot": per_shot}
    if target_seconds is not None:
        result["target_seconds"] = target_seconds
        result["within_limit"] = total <= target_seconds
        result["remaining_seconds"] = round(target_seconds - total, 1)
    return result


# ---------------------------------------------------------------- 规则检查

_EFFECT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%|提升\s*\d+|(\d+(?:\.\d+)?)\s*倍")


def _effect_claims(text: str) -> list[str]:
    return [m.group(0) for m in _EFFECT_RE.finditer(text)]


def check_rules(
    script: dict,
    retrieved_material_ids: list[str],
    rules: dict,
    platform: str | None = None,
    material_facts: dict[str, list[str]] | None = None,
) -> dict:
    """对照品牌规则检查脚本。

    material_facts：素材 ID → 事实列表。提供时按"分镜粒度"做事实溯源
    （该分镜旁白中的效果型结论必须来自该分镜自己引用的素材），
    未提供时退回 rules["_materials_facts"] 全局池（兼容直接调用）。
    返回 {"passed", "violations"(文本列表), "violation_details"(结构化明细)}。
    """
    violations: list[str] = []
    details: list[dict] = []
    retrieved = set(retrieved_material_ids)

    def _add(code: str, message: str, shot_idx: int | None = None) -> None:
        violations.append(message)
        details.append({"code": code, "shot_idx": shot_idx, "message": message})

    shots = script.get("shots", [])
    global_pool = " ".join(
        f for facts in rules.get("_materials_facts", []) for f in facts
    )

    # 1) 引用真实性 + 2) 分镜级事实溯源
    for shot in shots:
        idx = shot.get("idx")
        mids = shot.get("material_ids", [])
        for mid in mids:
            if mid not in retrieved:
                _add("unknown_material",
                     f"分镜{idx} 引用了未检索到的素材 {mid}", idx)

        narration = shot.get("narration", "")
        # 分镜池 = 该分镜引用素材的事实；无引用素材时为空
        if material_facts is not None:
            pool = " ".join(
                f for mid in mids for f in material_facts.get(mid, [])
            )
        else:
            pool = global_pool
        for claim in _effect_claims(narration):
            num = re.search(r"\d+(?:\.\d+)?", claim).group(0)
            if num not in pool:
                _add("unsupported_claim",
                     f"分镜{idx} 效果型结论无素材依据：「{claim}」", idx)

    # 3) 品牌禁用词（含标题）
    banned = rules.get("brand_banned_words", [])
    texts = [script.get("title", "")] + [s.get("narration", "") for s in shots]
    for w in banned:
        if any(w in t for t in texts):
            _add("banned_word", f"包含品牌禁用词：{w}")

    # 4) 标题中的效果型结论（标题无 material_ids，用本次检索全局池）
    for claim in _effect_claims(script.get("title", "")):
        num = re.search(r"\d+(?:\.\d+)?", claim).group(0)
        title_pool = global_pool
        if material_facts is not None:
            title_pool = " ".join(
                f for mid in retrieved for f in material_facts.get(mid, [])
            )
        if num not in title_pool:
            _add("unsupported_claim", f"标题效果型结论无素材依据：「{claim}」")

    # 5) 平台时长上限
    if platform and platform in rules.get("platform_rules", {}):
        limit = rules["platform_rules"][platform]["max_duration_sec"]
        total = estimate_duration(script)["total_seconds"]
        if total > limit:
            _add("platform_duration",
                 f"超出平台 {platform} 时长上限 {limit}s（当前 {total}s）")

    return {
        "passed": not violations,
        "violations": violations,
        "violation_details": details,
        "checked_shots": len(shots),
    }


# ---------------------------------------------------------------- 统一执行入口

TOOL_NAMES = ["search_materials", "estimate_duration", "check_rules"]


def execute_tool(
    name: str,
    args: dict,
    *,
    ctx: dict,
    fail_inject: set[str] | None = None,
) -> dict:
    """ReAct 循环的统一工具入口。

    ctx 需要包含：materials, rules, retrieved_ids（list，会被检索更新）、
    platform、target_seconds。
    fail_inject：要注入失败的工具名集合（测试/演示"工具失败"场景）。
    """
    if fail_inject and name in fail_inject:
        raise ToolError(f"{name} 执行失败（注入故障）：服务暂不可用")

    if name == "search_materials":
        query = args.get("query", "")
        hits = search_materials(query, ctx["materials"])
        ctx["retrieved_ids"] = sorted({*ctx.get("retrieved_ids", []), *[h["id"] for h in hits]})
        return {"hits": hits, "hit_count": len(hits), "query": query}

    if name == "estimate_duration":
        return estimate_duration(args.get("script", {}), ctx.get("target_seconds"))

    if name == "check_rules":
        return check_rules(
            args.get("script", {}),
            ctx.get("retrieved_ids", []),
            ctx["rules"],
            platform=ctx.get("platform"),
            material_facts=ctx.get("material_facts"),
        )

    raise ToolError(f"未知工具：{name}")
