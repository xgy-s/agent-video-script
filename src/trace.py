"""运行记录（Trace）：步骤、工具参数、返回摘要、后续动作及决策依据。"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


def _summarize(name: str, result: dict | None, error: str | None) -> str:
    """工具返回的简短摘要（Trace 不存全文，只留可核对要点）。"""
    if error:
        return f"ERROR: {error}"
    if name == "search_materials":
        ids = [h["id"] for h in result.get("hits", [])]
        return f"命中 {result.get('hit_count', 0)} 条素材: {ids}"
    if name == "estimate_duration":
        parts = [f"total={result.get('total_seconds')}s"]
        if "target_seconds" in result:
            parts.append(f"target={result['target_seconds']}s")
            parts.append(f"within_limit={result.get('within_limit')}")
        return " ".join(parts)
    if name == "check_rules":
        v = result.get("violations", [])
        return f"passed={result.get('passed')} violations={v if v else '[]'}"
    if name == "submit_script":
        n = len(result.get("script", {}).get("shots", []))
        return f"提交脚本：{n} 个分镜"
    return json.dumps(result, ensure_ascii=False)[:200]


class TraceRecorder:
    def __init__(self, task: dict):
        self.data = {
            "task": task,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "limits": {},
            "steps": [],
            "status": None,
            "output": None,
        }

    def set_limits(self, max_steps: int, max_tool_calls: int) -> None:
        self.data["limits"] = {"max_steps": max_steps, "max_tool_calls": max_tool_calls}

    def record(self, step: int, action: str, arguments: dict,
               result: dict | None = None, error: str | None = None,
               rationale: str = "") -> None:
        self.data["steps"].append({
            "step": step,
            "action": action,
            "arguments": arguments,
            "result_summary": _summarize(action, result, error),
            "rationale": rationale,  # 模型当步的决策依据（ assistant 消息文本）
        })

    def finish(self, status: str, output: dict | None) -> None:
        self.data["status"] = status
        self.data["output"] = output
        self.data["finished_at"] = datetime.now(timezone.utc).isoformat()

    def save(self, path: str | Path) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        return p
