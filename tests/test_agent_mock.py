"""ReAct 集成测试（Mock 模型驱动，确定性）：覆盖验收点 A1~A6。

Mock 仅验证流程与状态机，不证明真实模型决策效果；
真实模型路径见 examples/case1_normal_real.json 与 case5_over_duration_real.json。
"""
from src.agent import run_agent
from src.model import MockModelClient

BASE_TASK = {
    "topic": "便携榨汁杯",
    "audience": "上班族",
    "platform": "douyin",
    "duration": 60,
    "style": "活泼",
}


def _run(task=None, **kwargs):
    task = dict(BASE_TASK, **(task or {}))
    return run_agent(task, MockModelClient(task), **kwargs)


def _actions(result):
    return [s["action"] for s in result["trace"]["steps"]]


# ---------------------------------------------------------------- A1 正常生成

class TestNormalFlow:
    def test_completed_with_full_output(self):
        r = _run()
        assert r["status"] == "completed"
        out = r["output"]
        assert out["title"]
        assert len(out["shots"]) == 4
        assert 0 < out["total_seconds"] <= 60
        assert out["material_ids"]  # 素材来源非空
        assert out["note"] == "脚本草稿，未发布"

    def test_react_trajectory(self):
        r = _run()
        actions = _actions(r)
        assert actions == ["search_materials", "estimate_duration",
                           "check_rules", "submit_script"]

    def test_facts_cited_from_materials(self):
        r = _run()
        cited = {mid for s in r["output"]["shots"] for mid in s["material_ids"]}
        assert cited <= set(r["output"]["material_ids"])

    def test_per_shot_seconds_correspond(self):
        """审核点：分镜 → 时长 必须逐一对应且合计等于总时长。"""
        out = _run()["output"]
        per = out["per_shot_seconds"]
        assert len(per) == len(out["shots"])
        assert all(isinstance(v, float) and v > 0 for v in per.values())
        assert round(sum(per.values()), 1) == out["total_seconds"]
        # shots 内的 seconds 与 per_shot_seconds 一致
        for s in out["shots"]:
            assert s["seconds"] == per[s["idx"]]

    def test_checks_recorded(self):
        """审核点：检查结果必须随输出一并交付。"""
        out = _run()["output"]
        dur = out["checks"]["duration"]
        assert dur["within_limit"] is True
        assert dur["target_seconds"] == 60
        assert len(dur["per_shot"]) == len(out["shots"])
        rl = out["checks"]["rules"]
        assert rl["passed"] is True
        assert rl["violations"] == []
        assert rl["checked_shots"] == len(out["shots"])

    def test_each_shot_has_material_facts(self):
        """审核点：带素材 ID 的分镜能给出对应事实原文作为依据。"""
        out = _run()["output"]
        cited_shots = [s for s in out["shots"] if s["material_ids"]]
        assert cited_shots, "正常流程应有引用素材的分镜"
        for s in cited_shots:
            assert s["facts_from_materials"], f"分镜{s['idx']} 缺事实原文依据"


# ---------------------------------------------------------------- A2 缺关键信息

class TestMissingInfo:
    def test_missing_duration(self):
        r = _run({"duration": None})
        assert r["status"] == "needs_info"
        assert "duration" in r["output"]["missing_fields"]

    def test_missing_topic_and_duration(self):
        r = _run({"topic": None, "duration": None})
        assert r["status"] == "needs_info"
        assert set(r["output"]["missing_fields"]) == {"topic", "duration"}


# ---------------------------------------------------------------- A3 无素材

class TestNoMaterial:
    def test_unfinished_after_rewrite(self):
        r = _run({"topic": "不存在的商品xyz"})
        assert r["status"] == "unfinished"
        assert r["output"]["reason"] == "no_material"

    def test_two_search_attempts(self):
        r = _run({"topic": "不存在的商品xyz"})
        searches = [s for s in r["trace"]["steps"] if s["action"] == "search_materials"]
        assert len(searches) == 2
        # 第二次是改写后的更宽查询
        assert searches[1]["arguments"]["query"] != searches[0]["arguments"]["query"]


# ---------------------------------------------------------------- A4 工具失败

class TestToolFailure:
    def test_failed_after_retry(self):
        r = _run(fail_inject={"search_materials"})
        assert r["status"] == "failed"
        assert "search_materials" in r["output"]["reason"]

    def test_no_false_success(self):
        r = _run(fail_inject={"search_materials"})
        assert r["status"] != "completed"
        errors = [s for s in r["trace"]["steps"] if "ERROR" in s["result_summary"]]
        assert len(errors) >= 1  # 失败被如实记录


# ---------------------------------------------------------------- A5 超时长修正

class TestOverDurationRevise:
    def test_revise_then_completed(self):
        r = _run({"duration": 30})
        assert r["status"] == "completed"
        assert r["output"]["total_seconds"] <= 30

    def test_two_estimates_first_over_limit(self):
        r = _run({"duration": 30})
        estimates = [s for s in r["trace"]["steps"] if s["action"] == "estimate_duration"]
        assert len(estimates) == 2
        assert "within_limit=False" in estimates[0]["result_summary"]
        assert "within_limit=True" in estimates[1]["result_summary"]
        # 修正轨迹：估算 → 再估算 → 检查 → 提交
        assert _actions(r) == ["search_materials", "estimate_duration",
                               "estimate_duration", "check_rules", "submit_script"]


# ---------------------------------------------------------------- A6 步数上限保护

class TestStepLimit:
    def test_step_limit_returns_unfinished(self):
        r = _run(max_steps=2)
        assert r["status"] == "unfinished"
        assert r["output"]["reason"] == "step_limit"
        assert len(r["trace"]["steps"]) == 2

    def test_tool_call_limit_returns_unfinished(self):
        r = _run(max_tool_calls=1)
        assert r["status"] == "unfinished"
        assert r["output"]["reason"] == "tool_call_limit"
