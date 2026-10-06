from typing import Any

import pytest
from pydantic import ValidationError

from quickapp.common.synthetic_injection.injection_enums import InjectionFrequency
from quickapp.config.hooks import HookEvent, ToolCallHookConfig, TTLRefreshCondition


def _cfg(**overrides: Any) -> ToolCallHookConfig:
    data: dict[str, Any] = {"event": "on_request_start", "tool_name": "my_tool"}
    data.update(overrides)
    return ToolCallHookConfig(**data)


class TestOnCompletionEvent:
    def test_on_completion_accepted(self) -> None:
        cfg = _cfg(event="on_completion")
        assert cfg.event is HookEvent.ON_COMPLETION

    def test_explicit_frequency_rejected(self) -> None:
        with pytest.raises(ValidationError, match="frequency"):
            _cfg(event="on_completion", frequency="always")

    def test_explicit_default_frequency_still_rejected(self) -> None:
        with pytest.raises(ValidationError, match="frequency"):
            _cfg(event="on_completion", frequency=InjectionFrequency.APPEND_IF_CHANGED)

    def test_explicit_refresh_condition_rejected(self) -> None:
        with pytest.raises(ValidationError, match="refresh_condition"):
            _cfg(event="on_completion", refresh_condition={"kind": "ttl", "ttl_minutes": 5})

    def test_defaults_are_fine_on_completion(self) -> None:
        cfg = _cfg(event="on_completion", arguments={"q": "x"})
        assert cfg.refresh_condition is None

    def test_frequency_and_refresh_condition_still_valid_on_request_start(self) -> None:
        cfg = _cfg(frequency="always", refresh_condition={"kind": "ttl", "ttl_minutes": 5})
        assert cfg.frequency is InjectionFrequency.ALWAYS
        assert isinstance(cfg.refresh_condition, TTLRefreshCondition)


class TestTimeoutSeconds:
    def test_default_is_none(self) -> None:
        assert _cfg().timeout_seconds is None

    def test_positive_value_accepted(self) -> None:
        assert _cfg(event="on_completion", timeout_seconds=2.5).timeout_seconds == 2.5

    @pytest.mark.parametrize("value", [0, -1, -0.5])
    def test_non_positive_rejected(self, value: float) -> None:
        with pytest.raises(ValidationError, match="timeout_seconds"):
            _cfg(timeout_seconds=value)


class TestArgumentTemplates:
    def test_valid_template_on_request_start(self) -> None:
        _cfg(arguments={"q": "${last_user_message.content}"})

    def test_unknown_root_rejected(self) -> None:
        with pytest.raises(ValidationError, match="tool_input"):
            _cfg(event="on_completion", arguments={"q": "${tool_input}"})

    def test_typo_rejected(self) -> None:
        with pytest.raises(ValidationError, match="contnet"):
            _cfg(arguments={"q": "${last_user_message.contnet}"})

    def test_bad_syntax_rejected(self) -> None:
        with pytest.raises(ValidationError, match="invalid"):
            _cfg(arguments={"q": "${messages[}"})

    def test_eval_expression_validated(self) -> None:
        _cfg(arguments={"recent": {"$eval": "messages[-4:]"}})
        with pytest.raises(ValidationError, match="contnet"):
            _cfg(arguments={"q": {"$eval": "last_user_message.contnet"}})

    def test_other_json_e_operators_accepted(self) -> None:
        _cfg(
            arguments={
                "roles": {"$map": {"$eval": "messages"}, "each(m)": {"$eval": "m.role"}},
                "n": {"$if": "len(messages) > 1", "then": 1, "else": 0},
            }
        )

    def test_nested_template_validated(self) -> None:
        with pytest.raises(ValidationError, match="nope"):
            _cfg(arguments={"a": {"b": ["${nope}"]}})

    def test_iteration_count_ok_on_completion(self) -> None:
        _cfg(event="on_completion", arguments={"n": "${iteration_count}"})

    def test_iteration_count_rejected_on_request_start(self) -> None:
        with pytest.raises(ValidationError, match="iteration_count"):
            _cfg(arguments={"n": "${iteration_count}"})


class TestTemplateWithRefreshCondition:
    _TTL = {"kind": "ttl", "ttl_minutes": 10}

    def test_template_with_ttl_rejected(self) -> None:
        with pytest.raises(ValidationError, match="refresh_condition"):
            _cfg(arguments={"q": "${last_user_message.content}"}, refresh_condition=self._TTL)

    def test_literal_arguments_with_ttl_accepted(self) -> None:
        _cfg(arguments={"q": "literal"}, refresh_condition=self._TTL)

    def test_eval_with_ttl_rejected(self) -> None:
        with pytest.raises(ValidationError, match="refresh_condition"):
            _cfg(arguments={"q": {"$eval": "messages"}}, refresh_condition=self._TTL)

    def test_escaped_placeholder_with_ttl_accepted(self) -> None:
        _cfg(arguments={"q": "$${literal}"}, refresh_condition=self._TTL)
