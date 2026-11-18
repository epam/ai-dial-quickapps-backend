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
from pydantic import BaseModel, ConfigDict

TEMPERATURE_PARAM = "temperature"
MAX_TOKENS_PARAM = "max_tokens"
MAX_COMPLETION_TOKENS_PARAM = "max_completion_tokens"
REASONING_EFFORT_PARAM = "reasoning_effort"


class UnsupportedParameter(BaseModel):
    """A parameter removed from a request because the deployment does not support it."""

    model_config = ConfigDict(frozen=True)

    name: str
    value: Any
    # Completes "The AI model ... <reason>", e.g. "does not support `temperature`".
    reason: str


class _Drop(BaseModel):
    model_config = ConfigDict(frozen=True)

    reason: str


class _Rename(BaseModel):
    model_config = ConfigDict(frozen=True)

    to: str


_Verdict = _Drop | _Rename | None
_Rule = Callable[[Features, Any], _Verdict]


def _temperature_rule(features: Features, _value: Any) -> _Verdict:
    if features.temperature is False:
        return _Drop(reason=f"does not support `{TEMPERATURE_PARAM}`")
    if features.custom_temperature_supported is False:
        return _Drop(reason=f"does not support a custom `{TEMPERATURE_PARAM}`")
    return None


def _max_tokens_rule(features: Features, _value: Any) -> _Verdict:
    if features.max_tokens_supported is not False:
        return None
    # Renamed rather than dropped: dropping would lift the cap on the response length.
    if features.max_completion_tokens_supported is True:
        return _Rename(to=MAX_COMPLETION_TOKENS_PARAM)
    return _Drop(
        reason=f"supports neither `{MAX_TOKENS_PARAM}` nor `{MAX_COMPLETION_TOKENS_PARAM}`"
    )


def _reasoning_effort_rule(features: Features, value: Any) -> _Verdict:
    # An empty `reasoningEfforts` means no value is supported: a deployment that takes the
    # parameter is expected to list the values it takes.
    supported = features.reasoning_efforts
    if value in supported:
        return None
    if supported:
        return _Drop(reason="supports " + ", ".join(f"`{effort}`" for effort in supported))
    return _Drop(reason=f"does not advertise support for `{REASONING_EFFORT_PARAM}`")


_RULES: dict[str, _Rule] = {
    TEMPERATURE_PARAM: _temperature_rule,
    MAX_TOKENS_PARAM: _max_tokens_rule,
    REASONING_EFFORT_PARAM: _reasoning_effort_rule,
}

FEATURE_GATED_PARAMETERS: frozenset[str] = frozenset(_RULES)


def adapt_to_features(params: dict[str, Any], features: Features) -> list[UnsupportedParameter]:
    """Drop or rename, in place, the parameters `features` declares unsupported.

    Returns the dropped parameters. A rename (`max_tokens` to `max_completion_tokens`) keeps the
    value's effect, so it is not reported; a value already set under the new name wins.
    """
    dropped: list[UnsupportedParameter] = []
    for name, rule in _RULES.items():
        value = params.get(name)
        if value is None:
            continue
        verdict = rule(features, value)
        if isinstance(verdict, _Rename):
            del params[name]
            params.setdefault(verdict.to, value)
        elif isinstance(verdict, _Drop):
            del params[name]
            dropped.append(UnsupportedParameter(name=name, value=value, reason=verdict.reason))
    return dropped
