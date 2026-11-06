"""QwenClient 参数容错解析单测（不访问网络）。"""
import pytest

from src.model import _close_truncated_json, _parse_arguments


class TestParseArguments:
    def test_normal_json(self):
        assert _parse_arguments('{"query": "榨汁"}') == {"query": "榨汁"}

    def test_empty_defaults_to_empty_dict(self):
        assert _parse_arguments(None) == {}
        assert _parse_arguments("") == {}

    def test_control_chars_in_string(self):
        # 字符串内含原始换行：strict 失败，strict=False 成功
        raw = '{"narration": "第一行\n第二行"}'
        assert _parse_arguments(raw) == {"narration": "第一行\n第二行"}

    def test_truncated_missing_closing_brace(self):
        # 复现真实故障：qwen 输出尾部少一个 `}`
        raw = '{"script": {"title": "t", "shots": [{"idx": 1, "material_ids": ["P01"]}]}'
        assert _parse_arguments(raw) == {
            "script": {"title": "t", "shots": [{"idx": 1, "material_ids": ["P01"]}]}
        }

    def test_truncated_mid_string(self):
        raw = '{"query": "便携榨'
        assert _parse_arguments(raw) == {"query": "便携榨"}

    def test_unrecoverable_raises(self):
        with pytest.raises(Exception):
            _parse_arguments("{not json at all")


class TestCloseTruncatedJson:
    def test_balanced_unchanged(self):
        assert _close_truncated_json('{"a": [1, 2]}') == '{"a": [1, 2]}'

    def test_escaped_quote_not_counted(self):
        # \" 不切换字符串状态：尾部 } 在串内 → 视为串未闭合，补 " 和 }
        assert _close_truncated_json('{"a": "x\\"}') == '{"a": "x\\"}"}'
