import json

import pytest

from quickapp.tool_discovery._routing_prompt import (
    build_response_format,
    build_system_prompt,
    parse_selection,
)

KNOWN = {"tool_a", "tool_b", "tool_c"}


def _answer(matches_json: str) -> str:
    return '{"matches": ' + matches_json + "}"


def _parse(raw: str, limit: int = 10, threshold: float = 0.5) -> list[str]:
    return [item.name for item in parse_selection(raw, KNOWN, limit=limit, threshold=threshold)]


def _parse_matches(matches_json: str, **kwargs) -> list[str]:
    return _parse(_answer(matches_json), **kwargs)


class TestParseSelection:
    def test_sorts_by_score_and_applies_threshold_and_limit(self):
        raw = _answer(
            json.dumps(
                [
                    {"name": "tool_a", "score": 0.6},
                    {"name": "tool_b", "score": 0.9},
                    {"name": "tool_c", "score": 0.2},
                ]
            )
        )
        assert _parse(raw) == ["tool_b", "tool_a"]
        assert _parse(raw, limit=1) == ["tool_b"]

    def test_drops_unknown_names_and_keeps_best_score_of_duplicates(self):
        raw = (
            '[{"name": "ghost", "score": 1}, {"name": "tool_a", "score": 0.1},'
            ' {"name": "tool_a", "score": 0.8}]'
        )
        assert _parse_matches(raw) == ["tool_a"]

    def test_clamps_score_to_unit_range(self):
        raw = '[{"name": "tool_a", "score": 7}, {"name": "tool_b", "score": 0.9}]'
        parsed = parse_selection(_answer(raw), KNOWN, limit=10, threshold=0.5)
        assert [(item.name, item.score) for item in parsed] == [("tool_a", 1.0), ("tool_b", 0.9)]

    def test_empty_matches_yield_empty(self):
        assert _parse_matches("[]") == []

    @pytest.mark.parametrize(
        "raw",
        [
            "not json",
            '{"matches": [1, 2',
            "",
            "{}",
            '{"matches": "tool_a"}',
            '["tool_a"]',
            '```json\n{"matches": []}\n```',
            '{"matches": ["tool_a"]}',
            '{"matches": [{"name": "tool_a"}]}',
            '{"matches": [{"name": "tool_a", "score": "high"}]}',
            '{"matches": [{"name": "tool_a", "score": null}]}',
            '{"matches": [{"name": "tool_a", "score": NaN}]}',
            '{"matches": [{"name": "tool_a", "score": 1, "extra": 1}]}',
        ],
    )
    def test_answer_not_matching_the_schema_yields_empty(self, raw):
        assert _parse(raw) == []


class TestBuildSystemPrompt:
    def test_asks_for_the_same_object_format_the_schema_describes(self):
        prompt = build_system_prompt([{"name": "tool_a", "description": "A"}], "tool", 3)

        assert '{"matches": [{"name": "<tool name>", "score": <number 0..1>}]}' in prompt
        assert "- tool_a: A" in prompt


class TestBuildResponseFormat:
    def test_schema_is_strict_inlined_and_names_are_plain_strings(self):
        spec = build_response_format()["json_schema"]
        schema = spec["schema"]
        item = schema["properties"]["matches"]["items"]

        assert spec["strict"] is True
        assert "$defs" not in schema
        assert schema["additionalProperties"] is False
        assert schema["required"] == ["matches"]
        assert item["additionalProperties"] is False
        assert item["required"] == ["name", "score"]
        assert item["properties"]["name"]["type"] == "string"
        assert "enum" not in item["properties"]["name"]
