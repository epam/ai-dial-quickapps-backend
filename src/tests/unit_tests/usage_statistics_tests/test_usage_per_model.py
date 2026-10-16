from unittest.mock import MagicMock, call

from aidial_sdk.chat_completion import Response

from quickapp.common.deployment_usage import DeploymentUsage
from quickapp.usage_statistics.usage_per_model import (
    aggregate_usage_per_model,
    report_usage_per_model,
)


def _usage(model: str, prompt: int, completion: int, name: str = "Orchestrator") -> DeploymentUsage:
    return DeploymentUsage(
        deployment_id=model if name != "Orchestrator" else "Orchestrator",
        deployment_name=name,
        model_name=model,
        prompt_tokens=prompt,
        completion_tokens=completion,
    )


def test_aggregate_sums_tokens_per_model_in_first_seen_order():
    usages = [
        _usage("gpt-5", 100, 10),
        _usage("gpt-image-1", 5, 40, name="image_tool"),
        _usage("gpt-5", 50, 5),
        _usage("gpt-image-1", 1, 2, name="image_tool"),
    ]

    result = aggregate_usage_per_model(usages)

    assert [(m.model, m.prompt_tokens, m.completion_tokens) for m in result] == [
        ("gpt-5", 150, 15),
        ("gpt-image-1", 6, 42),
    ]


def test_aggregate_of_nothing_is_empty():
    assert aggregate_usage_per_model([]) == []


def test_report_adds_one_entry_per_model():
    response = MagicMock(spec=Response)

    report_usage_per_model(response, [_usage("gpt-5", 100, 10), _usage("gpt-image-1", 5, 40, "t")])

    assert response.add_usage_per_model.call_args_list == [
        call("gpt-5", 100, 10),
        call("gpt-image-1", 5, 40),
    ]


def test_report_without_usage_adds_nothing():
    response = MagicMock(spec=Response)

    report_usage_per_model(response, [])

    response.add_usage_per_model.assert_not_called()
