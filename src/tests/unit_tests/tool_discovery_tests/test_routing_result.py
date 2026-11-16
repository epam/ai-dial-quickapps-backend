from quickapp.common.deployment_usage import ModelUsage
from quickapp.tool_discovery._routing_result import RoutingResult


def _usage(prompt: int, completion: int) -> ModelUsage:
    return ModelUsage(model="m1", prompt_tokens=prompt, completion_tokens=completion)


class TestCombine:
    def test_totals_usage_and_keeps_given_names(self):
        result = RoutingResult.combine(
            ["a"],
            RoutingResult(names=["x"], usage=_usage(10, 1)),
            RoutingResult(names=["y"], usage=_usage(5, 2)),
        )

        assert result.names == ["a"]
        assert result.usage == _usage(15, 3)

    def test_deduplicates_warnings_keeping_order(self):
        result = RoutingResult.combine(
            [],
            RoutingResult(warnings=["w1", "w2"]),
            RoutingResult(warnings=["w1"]),
            RoutingResult(),
        )

        assert result.warnings == ["w1", "w2"]
        assert result.usage is None
