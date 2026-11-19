from typing import Any

import pytest
from aidial_client.types.deployment import Features

from quickapp.common.deployment_parameter_support import (
    FEATURE_GATED_PARAMETERS,
    remove_unsupported_parameters,
    unsupported_parameters,
)


class TestTemperature:
    @pytest.mark.parametrize(
        "features",
        [
            Features(),
            Features(temperature=True, custom_temperature_supported=True),
        ],
        ids=["flags_unknown", "flags_true"],
    )
    def test_supported_unless_a_flag_is_false(self, features: Features):
        assert unsupported_parameters({"temperature": 0.2}, features) == []

    @pytest.mark.parametrize(
        "features",
        [Features(temperature=False), Features(custom_temperature_supported=False)],
        ids=["temperature_unsupported", "custom_temperature_unsupported"],
    )
    def test_unsupported_when_a_flag_is_false(self, features: Features):
        assert unsupported_parameters({"temperature": 0.2}, features) == ["temperature"]


class TestReasoningEffort:
    def test_supported_when_advertised(self):
        features = Features(reasoning_efforts=["low", "high"])

        assert unsupported_parameters({"reasoning_effort": "high"}, features) == []

    def test_unsupported_when_not_advertised(self):
        features = Features(reasoning_efforts=["low", "medium"])

        assert unsupported_parameters({"reasoning_effort": "high"}, features) == [
            "reasoning_effort"
        ]

    def test_unsupported_when_deployment_advertises_none(self):
        """An empty list means no value is supported, not that every value is."""
        assert unsupported_parameters({"reasoning_effort": "low"}, Features()) == [
            "reasoning_effort"
        ]


def test_ungated_parameters_are_never_unsupported():
    """`seed` is not enforced: Core defaults `seedSupported` to false, so it can't tell
    "unsupported" from "never configured"."""
    params = {"seed": 7, "top_p": 1, "stop": ["x"], "custom_fields": {}}

    assert unsupported_parameters(params, Features(seed=False)) == []


def test_none_values_are_ignored():
    assert unsupported_parameters({"temperature": None}, Features(temperature=False)) == []


def test_unsupported_parameters_does_not_mutate():
    params = {"temperature": 0.2, "seed": 7}

    unsupported_parameters(params, Features(temperature=False))

    assert params == {"temperature": 0.2, "seed": 7}


def test_remove_unsupported_parameters_removes_in_place():
    params: dict[str, Any] = {"temperature": 0.2, "reasoning_effort": "high", "seed": 7}

    remove_unsupported_parameters(params, Features(temperature=False, reasoning_efforts=["high"]))

    assert params == {"reasoning_effort": "high", "seed": 7}


def test_gated_parameters_are_the_ruled_ones():
    assert FEATURE_GATED_PARAMETERS == {"temperature", "reasoning_effort"}
