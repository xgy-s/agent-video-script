"""CLI 入口。

示例：
  python -m src.cli --topic "便携榨汁杯" --audience "上班族" --platform douyin --duration 30 --style "活泼"
  python -m src.cli --mock --topic "便携榨汁杯" --duration 60
  python -m src.cli --mock --topic "榨汁" --fail-inject search_materials   # 演示工具失败
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:  # python-dotenv 为可选依赖：--mock 离线模式零依赖可跑
    from dotenv import load_dotenv as _load_dotenv_safe
except ImportError:
    def _load_dotenv_safe() -> bool:
        return False

from .agent import DEFAULT_MAX_STEPS, DEFAULT_MAX_TOOL_CALLS, run_agent
from .model import MockModelClient, QwenClient


def main() -> int:
    _load_dotenv_safe()
    p = argparse.ArgumentParser(description="短视频脚本 Agent（题 4）")
    p.add_argument("--topic", help="脚本主题")
    p.add_argument("--audience", default="", help="目标受众")
    p.add_argument("--platform", default="douyin", help="平台：douyin/kuaishou/xiaohongshu")
    p.add_argument("--duration", type=int, help="目标时长（秒）")
    p.add_argument("--style", default="", help="风格")
    p.add_argument("--mock", action="store_true", help="离线 Mock 模式（仅验证流程）")
    p.add_argument("--model", help="覆盖模型名，默认 env QWEN_MODEL 或 qwen-plus")
    p.add_argument("--max-steps", type=int, default=DEFAULT_MAX_STEPS)
    p.add_argument("--max-tool-calls", type=int, default=DEFAULT_MAX_TOOL_CALLS)
    p.add_argument("--fail-inject", nargs="*", default=[],
                   help="注入失败的工具名（演示工具失败场景）")
    p.add_argument("--out", help="Trace 输出路径（如 examples/case1_normal.json）")
    args = p.parse_args()

    task = {
        "topic": args.topic,
        "audience": args.audience,
        "platform": args.platform,
        "duration": args.duration,
        "style": args.style,
    }

    if args.mock:
        client = MockModelClient(task)
        mode = "mock"
    else:
        client = QwenClient(model=args.model)
        mode = f"qwen:{client.model}"

    result = run_agent(
        task, client,
        max_steps=args.max_steps,
        max_tool_calls=args.max_tool_calls,
        fail_inject=set(args.fail_inject),
    )

    if args.out:
        p = Path(args.out)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(result["trace"], ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[trace] {p}")

    print(f"[mode] {mode}")
    print(f"[status] {result['status']}")
    print(json.dumps(result["output"], ensure_ascii=False, indent=2))
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())
