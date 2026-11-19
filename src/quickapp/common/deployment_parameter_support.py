"""Shape chat-completion parameters by the target deployment's DialCore features.

A deployment advertises in `features` which request parameters its upstream accepts (Core
`temperatureSupported`, `maxTokensSupported`, `reasoningEfforts`, ...). Core forwards a request
unchanged, so a parameter the upstream rejects fails the call with an opaque `400` that reaches
the user as a generic "request was rejected as invalid". DIAL Chat leaves such parameters out;
this module does the same for the orchestrator and for deployment tools.

Only flags Core defaults to `true` are enforced, because for those `false` means an admin turned
the parameter off. A default-`false` flag such as `seedSupported` cannot tell "unsupported" from
"never configured", so `seed` passes through, as do parameters Core has no flag for.
"""

from collections.abc import Callable
from typing import Any

from aidial_client.types.deployment import Features

TEMPERATURE_PARAM = "temperature"
MAX_TOKENS_PARAM = "max_tokens"
MAX_COMPLETION_TOKENS_PARAM = "max_completion_tokens"
REASONING_EFFORT_PARAM = "reasoning_effort"

# A rule returns the name the value is sent under, or `None` when the parameter is dropped.
_Rule = Callable[[Features, Any], str | None]


def _temperature_rule(features: Features, _value: Any) -> str | None:
    if features.temperature is False or features.custom_temperature_supported is False:
        return None
    return TEMPERATURE_PARAM


def _max_tokens_rule(features: Features, _value: Any) -> str | None:
    if features.max_tokens_supported is not False:
        return MAX_TOKENS_PARAM
    # Renamed rather than dropped: dropping would lift the cap on the response length.
    if features.max_completion_tokens_supported is True:
        return MAX_COMPLETION_TOKENS_PARAM
    return None


def _reasoning_effort_rule(features: Features, value: Any) -> str | None:
    # An empty `reasoningEfforts` means no value is supported: a deployment that takes the
    # parameter is expected to list the values it takes.
    return REASONING_EFFORT_PARAM if value in features.reasoning_efforts else None


_RULES: dict[str, _Rule] = {
    TEMPERATURE_PARAM: _temperature_rule,
    MAX_TOKENS_PARAM: _max_tokens_rule,
    REASONING_EFFORT_PARAM: _reasoning_effort_rule,
}

FEATURE_GATED_PARAMETERS: frozenset[str] = frozenset(_RULES)


def adapt_to_features(params: dict[str, Any], features: Features) -> list[str]:
    """Drop or rename, in place, the parameters `features` declares unsupported.

    Returns the names of the dropped parameters. A rename (`max_tokens` to
    `max_completion_tokens`) keeps the value's effect, so it is not reported; a value already set
    under the new name wins.
    """
    dropped: list[str] = []
    for name, rule in _RULES.items():
        value = params.get(name)
        if value is None:
            continue
        target = rule(features, value)
        if target == name:
            continue
        del params[name]
        if target is None:
            dropped.append(name)
        else:
            params.setdefault(target, value)
    return dropped
