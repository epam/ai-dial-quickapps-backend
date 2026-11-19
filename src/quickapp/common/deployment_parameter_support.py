"""Drop chat-completion parameters the target deployment's DialCore features declare unsupported.

A deployment advertises in `features` which request parameters its upstream accepts (Core
`temperatureSupported`, `reasoningEfforts`, ...). Core forwards a request unchanged, so a
parameter the upstream rejects fails the call with an opaque `400` that reaches the user as a
generic "request was rejected as invalid". This module leaves such parameters out for the
orchestrator and for deployment tools.

Boolean flags are enforced only when Core defaults them to `true`, because for those `false` means
an admin turned the parameter off. A default-`false` flag such as `seedSupported` cannot tell
"unsupported" from "never configured", so `seed` passes through, as do parameters Core has no flag
for. `reasoningEfforts` is the exception: Core defines an empty list as "not supported".
"""

from collections.abc import Callable
from typing import Any

from aidial_client.types.deployment import Features

TEMPERATURE_PARAM = "temperature"
REASONING_EFFORT_PARAM = "reasoning_effort"

# A rule tells whether the deployment accepts the configured value.
_Rule = Callable[[Features, Any], bool]


def _temperature_rule(features: Features, _value: Any) -> bool:
    # `customTemperatureSupported=false` accepts only the API default, which leaving the
    # parameter out yields anyway.
    return features.temperature is not False and features.custom_temperature_supported is not False


def _reasoning_effort_rule(features: Features, value: Any) -> bool:
    # An empty `reasoningEfforts` means no value is supported: a deployment that takes the
    # parameter is expected to list the values it takes.
    return value in features.reasoning_efforts


_RULES: dict[str, _Rule] = {
    TEMPERATURE_PARAM: _temperature_rule,
    REASONING_EFFORT_PARAM: _reasoning_effort_rule,
}

FEATURE_GATED_PARAMETERS: frozenset[str] = frozenset(_RULES)


def drop_unsupported(params: dict[str, Any], features: Features) -> list[str]:
    """Remove, in place, the parameters `features` declares unsupported; return their names."""
    dropped: list[str] = []
    for name, rule in _RULES.items():
        value = params.get(name)
        if value is not None and not rule(features, value):
            del params[name]
            dropped.append(name)
    return dropped
