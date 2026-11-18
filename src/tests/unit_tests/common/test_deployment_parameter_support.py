from typing import Any

import pytest
from aidial_client.types.deployment import Features

from quickapp.common.deployment_parameter_support import (
    FEATURE_GATED_PARAMETERS,
    UnsupportedParameter,
    adapt_to_features,
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

        assert adapt_to_features(params, features) == []
        assert params == {"temperature": 0.2}

    def test_dropped_when_temperature_is_unsupported(self):
        params: dict[str, Any] = {"temperature": 0.2}

        dropped = adapt_to_features(params, Features(temperature=False))

        assert params == {}
        assert dropped == [
            UnsupportedParameter(
                name="temperature", value=0.2, reason="does not support `temperature`"
            )
        ]

    def test_dropped_when_custom_temperature_is_unsupported(self):
        params: dict[str, Any] = {"temperature": 0.2}

        dropped = adapt_to_features(params, Features(custom_temperature_supported=False))

        assert params == {}
        assert dropped[0].reason == "does not support a custom `temperature`"


class TestMaxTokens:
    def test_kept_unless_max_tokens_is_unsupported(self):
        params: dict[str, Any] = {"max_tokens": 100}

        assert adapt_to_features(params, Features()) == []
        assert params == {"max_tokens": 100}

    def test_renamed_when_only_max_completion_tokens_is_supported(self):
        params: dict[str, Any] = {"max_tokens": 100}
        features = Features(max_tokens_supported=False, max_completion_tokens_supported=True)

        assert adapt_to_features(params, features) == []
        assert params == {"max_completion_tokens": 100}

    def test_rename_keeps_an_explicit_max_completion_tokens(self):
        params: dict[str, Any] = {"max_tokens": 100, "max_completion_tokens": 50}
        features = Features(max_tokens_supported=False, max_completion_tokens_supported=True)

        adapt_to_features(params, features)

        assert params == {"max_completion_tokens": 50}

    def test_dropped_when_neither_is_supported(self):
        params: dict[str, Any] = {"max_tokens": 100}

        dropped = adapt_to_features(params, Features(max_tokens_supported=False))

        assert params == {}
        assert [d.name for d in dropped] == ["max_tokens"]


class TestReasoningEffort:
    def test_kept_when_advertised(self):
        params: dict[str, Any] = {"reasoning_effort": "high"}

        assert adapt_to_features(params, Features(reasoning_efforts=["low", "high"])) == []
        assert params == {"reasoning_effort": "high"}

    def test_dropped_when_not_advertised(self):
        params: dict[str, Any] = {"reasoning_effort": "high"}

        dropped = adapt_to_features(params, Features(reasoning_efforts=["low", "medium"]))

        assert params == {}
        assert dropped[0].reason == "supports `low`, `medium`"

    def test_dropped_when_deployment_advertises_none(self):
        """An empty list means no value is supported, not that every value is."""
        params: dict[str, Any] = {"reasoning_effort": "low"}

        dropped = adapt_to_features(params, Features())

        assert params == {}
        assert dropped[0].reason == "does not advertise support for `reasoning_effort`"


def test_ungated_parameters_pass_through():
    """`seed` is not enforced: Core defaults `seedSupported` to false, so it can't tell
    "unsupported" from "never configured"."""
    params: dict[str, Any] = {"seed": 7, "top_p": 1, "stop": ["x"], "custom_fields": {}}

    assert adapt_to_features(params, Features(seed=False)) == []
    assert params == {"seed": 7, "top_p": 1, "stop": ["x"], "custom_fields": {}}


def test_none_values_are_ignored():
    params: dict[str, Any] = {"temperature": None}

    assert adapt_to_features(params, Features(temperature=False)) == []
    assert params == {"temperature": None}


def test_gated_parameters_are_the_ruled_ones():
    assert FEATURE_GATED_PARAMETERS == {"temperature", "max_tokens", "reasoning_effort"}
