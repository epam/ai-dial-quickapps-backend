from typing import Any

import pytest
from aidial_client.types.deployment import Features

from quickapp.common.deployment_parameter_support import (
    FEATURE_GATED_PARAMETERS,
    remove_unsupported_parameters,
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
    def test_kept_unless_a_flag_is_false(self, features: Features):
        params: dict[str, Any] = {"temperature": 0.2}

        assert remove_unsupported_parameters(params, features) == []
        assert params == {"temperature": 0.2}

    @pytest.mark.parametrize(
        "features",
        [Features(temperature=False), Features(custom_temperature_supported=False)],
        ids=["temperature_unsupported", "custom_temperature_unsupported"],
    )
    def test_dropped_when_a_flag_is_false(self, features: Features):
        params: dict[str, Any] = {"temperature": 0.2, "seed": 7}

        assert remove_unsupported_parameters(params, features) == ["temperature"]
        assert params == {"seed": 7}


class TestReasoningEffort:
    def test_kept_when_advertised(self):
        params: dict[str, Any] = {"reasoning_effort": "high"}

        assert (
            remove_unsupported_parameters(params, Features(reasoning_efforts=["low", "high"])) == []
        )
        assert params == {"reasoning_effort": "high"}

    def test_dropped_when_not_advertised(self):
        params: dict[str, Any] = {"reasoning_effort": "high"}

        assert remove_unsupported_parameters(
            params, Features(reasoning_efforts=["low", "medium"])
        ) == ["reasoning_effort"]
        assert params == {}

    def test_dropped_when_deployment_advertises_none(self):
        """An empty list means no value is supported, not that every value is."""
        params: dict[str, Any] = {"reasoning_effort": "low"}

        assert remove_unsupported_parameters(params, Features()) == ["reasoning_effort"]
        assert params == {}


def test_ungated_parameters_pass_through():
    """`seed` is not enforced: Core defaults `seedSupported` to false, so it can't tell
    "unsupported" from "never configured"."""
    params: dict[str, Any] = {"seed": 7, "top_p": 1, "stop": ["x"], "custom_fields": {}}

    assert remove_unsupported_parameters(params, Features(seed=False)) == []
    assert params == {"seed": 7, "top_p": 1, "stop": ["x"], "custom_fields": {}}


def test_none_values_are_ignored():
    params: dict[str, Any] = {"temperature": None}

    assert remove_unsupported_parameters(params, Features(temperature=False)) == []
    assert params == {"temperature": None}


def test_gated_parameters_are_the_ruled_ones():
    assert FEATURE_GATED_PARAMETERS == {"temperature", "reasoning_effort"}
