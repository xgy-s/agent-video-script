"""tools.py 单元测试：检索 / 时长估算 / 规则检查 / 失败注入。"""
import pytest

from src.tools import (
    CHARS_PER_SEC,
    SHOT_BUFFER_SEC,
    ToolError,
    check_rules,
    estimate_duration,
    execute_tool,
    load_materials,
    load_rules,
    search_materials,
)


@pytest.fixture(scope="module")
def materials():
    return load_materials()


@pytest.fixture(scope="module")
def rules():
    return load_rules()


def _script(narrations, material_ids=None):
    return {
        "title": "测试脚本",
        "shots": [
            {
                "idx": i + 1,
                "visual": "画面",
                "narration": n,
                "material_ids": material_ids or [],
            }
            for i, n in enumerate(narrations)
        ],
    }


# ---------------------------------------------------------------- 检索

class TestSearchMaterials:
    def test_hit_by_keyword(self, materials):
        hits = search_materials("榨汁", materials)
        ids = {h["id"] for h in hits}
        assert {"P01", "P02", "P05"} <= ids

    def test_hit_by_product_name(self, materials):
        hits = search_materials("便携榨汁杯", materials)
        assert {h["id"] for h in hits} == {"P01", "P02", "P05"}

    def test_no_hit(self, materials):
        assert search_materials("不存在的商品xyz", materials) == []

    def test_hit_contains_facts(self, materials):
        hits = search_materials("降噪", materials)
        assert hits[0]["id"] == "P04"
        assert any("35dB" in f for f in hits[0]["facts"])


# ---------------------------------------------------------------- 时长估算

class TestEstimateDuration:
    def test_formula(self):
        script = _script(["一二三四五六七八九"])  # 9 字
        est = estimate_duration(script)
        expected = round(9 / CHARS_PER_SEC + SHOT_BUFFER_SEC, 1)
        assert est["per_shot"][0]["seconds"] == expected
        assert est["total_seconds"] == expected

    def test_total_is_sum_of_shots(self):
        script = _script(["一二三四五六七八九", "一二三四五六七八九一二三四五六七八九"])
        est = estimate_duration(script)
        assert est["total_seconds"] == round(sum(s["seconds"] for s in est["per_shot"]), 1)

    def test_within_limit_flag(self):
        script = _script(["一二三四五六七八九"])  # ~3.5s
        assert estimate_duration(script, 10)["within_limit"] is True
        assert estimate_duration(script, 1)["within_limit"] is False

    def test_no_target_has_no_flag(self):
        assert "within_limit" not in estimate_duration(_script(["abc"]))


# ---------------------------------------------------------------- 规则检查

class TestCheckRules:
    def test_pass_clean_script(self, rules):
        script = _script(["杯身 450ml，重量 380g，可放入通勤包侧袋"], ["P01"])
        result = check_rules(script, ["P01"], rules, platform="douyin")
        assert result["passed"], result["violations"]

    def test_banned_word(self, rules):
        script = _script(["这是最好的榨汁杯"], ["P01"])
        result = check_rules(script, ["P01"], rules)
        assert not result["passed"]
        assert any("禁用词" in v for v in result["violations"])

    def test_unknown_material_id(self, rules):
        script = _script(["引用不存在的素材"], ["P99"])
        result = check_rules(script, ["P01"], rules)
        assert not result["passed"]
        assert any("P99" in v for v in result["violations"])

    def test_effect_claim_without_basis(self, rules):
        script = _script(["效率提升80%，遥遥领先"], ["P01"])
        result = check_rules(script, ["P01"], rules)
        assert not result["passed"]
        assert any("无素材依据" in v for v in result["violations"])

    def test_effect_claim_with_basis(self, rules):
        # "满电可榨 8 杯" 是 P01 原文；8 杯不匹配效果正则，不触发违规
        script = _script(["支持 USB-C 充电，满电可榨 8 杯"], ["P01"])
        rules2 = dict(rules)
        rules2["_materials_facts"] = [["支持 USB-C 充电，满电可榨 8 杯"]]
        result = check_rules(script, ["P01"], rules2, platform="douyin")
        assert result["passed"], result["violations"]

    def test_platform_duration_limit(self, rules):
        long_narration = "字" * 300  # ~68s，超 douyin 60s
        script = _script([long_narration], ["P01"])
        douyin = check_rules(script, ["P01"], rules, platform="douyin")
        xhs = check_rules(script, ["P01"], rules, platform="xiaohongshu")
        assert not douyin["passed"]
        assert any("时长上限" in v for v in douyin["violations"])
        assert xhs["passed"]  # 小红书 90s 上限不触发

    def test_shot_level_fact_traceability(self, rules):
        """分镜粒度溯源：数字依据必须来自该分镜自己引用的素材。"""
        facts = {
            "P01": ["杯身 450ml，重量 380g，可放入通勤包侧袋"],
            "P05": ["续航提升 20%"],
        }
        script = {
            "title": "测试",
            "shots": [
                # 引用 P01，但其 facts 中没有「20%」→ 违规
                {"idx": 1, "visual": "a", "narration": "续航提升20%",
                 "material_ids": ["P01"]},
                # 引用 P05，其 facts 中有「20%」→ 合规
                {"idx": 2, "visual": "b", "narration": "续航提升20%",
                 "material_ids": ["P05"]},
            ],
        }
        result = check_rules(script, ["P01", "P05"], rules,
                             material_facts=facts)
        assert not result["passed"]
        assert [d["shot_idx"] for d in result["violation_details"]
                if d["code"] == "unsupported_claim"] == [1]

    def test_shot_level_no_source_claim_fails(self, rules):
        """分镜未引用任何素材却含效果型结论 → 违规（无来源即编造）。"""
        facts = {"P01": ["杯身 450ml"]}
        script = _script(["效率提升80%"], [])
        result = check_rules(script, ["P01"], rules, material_facts=facts)
        assert not result["passed"]
        assert result["violation_details"][0]["shot_idx"] == 1

    def test_shot_level_pass_when_fact_matches(self, rules):
        facts = {"P01": ["杯身 450ml，重量 380g，可放入通勤包侧袋"]}
        script = _script(["杯身 450ml，重量 380g，可放入通勤包侧袋"], ["P01"])
        result = check_rules(script, ["P01"], rules, material_facts=facts)
        assert result["passed"], result["violations"]
        assert result["checked_shots"] == 1

    def test_violation_details_structured(self, rules):
        script = _script(["这是最好的产品"], ["P99"])
        result = check_rules(script, ["P01"], rules)
        codes = {d["code"] for d in result["violation_details"]}
        assert "banned_word" in codes
        assert "unknown_material" in codes


# ---------------------------------------------------------------- 统一入口 / 失败注入

class TestExecuteTool:
    def _ctx(self, materials, rules):
        return {
            "materials": materials,
            "rules": dict(rules),
            "retrieved_ids": [],
            "platform": "douyin",
            "target_seconds": 60,
        }

    def test_search_updates_retrieved_ids(self, materials, rules):
        ctx = self._ctx(materials, rules)
        result = execute_tool("search_materials", {"query": "榨汁"}, ctx=ctx)
        assert result["hit_count"] >= 3
        assert set(ctx["retrieved_ids"]) == {"P01", "P02", "P05"}

    def test_fail_inject_raises_tool_error(self, materials, rules):
        ctx = self._ctx(materials, rules)
        with pytest.raises(ToolError):
            execute_tool("search_materials", {"query": "榨汁"},
                         ctx=ctx, fail_inject={"search_materials"})

    def test_unknown_tool(self, materials, rules):
        with pytest.raises(ToolError):
            execute_tool("hack", {}, ctx=self._ctx(materials, rules))
