import json

import pytest

from quickapp.tool_discovery._routing_prompt import parse_selection

KNOWN = {"tool_a", "tool_b", "tool_c"}


def _parse(raw: str, limit: int = 10, threshold: float = 0.5) -> list[str]:
    return [item.name for item in parse_selection(raw, KNOWN, limit=limit, threshold=threshold)]


class TestParseSelection:
    def test_sorts_by_score_and_applies_threshold_and_limit(self):
        raw = json.dumps(
            [
                {"name": "tool_a", "score": 0.6},
                {"name": "tool_b", "score": 0.9},
                {"name": "tool_c", "score": 0.2},
            ]
        )
        assert _parse(raw) == ["tool_b", "tool_a"]
        assert _parse(raw, limit=1) == ["tool_b"]

    def test_strips_fences_and_accepts_plain_names(self):
        assert _parse('```json\n["tool_a", "tool_b"]\n```') == ["tool_a", "tool_b"]

    def test_drops_unknown_and_duplicate_names(self):
        assert _parse('["ghost", "tool_a", "tool_a", 5]') == ["tool_a"]

    def test_keeps_best_score_of_duplicates(self):
        raw = '[{"name": "tool_a", "score": 0.1}, {"name": "tool_a", "score": 0.8}]'
        assert _parse(raw) == ["tool_a"]

    @pytest.mark.parametrize("raw", ["not json", "[1, 2", "", "{}"])
    def test_unparsable_answer_yields_empty(self, raw):
        assert _parse(raw) == []

    def test_numeric_string_score_is_compared_to_threshold(self):
        raw = '[{"name": "tool_a", "score": "0.2"}, {"name": "tool_b", "score": "0.9"}]'
        assert _parse(raw) == ["tool_b"]

    def test_unreadable_score_counts_as_perfect_fit(self):
        assert _parse('[{"name": "tool_a", "score": "high"}]') == ["tool_a"]
