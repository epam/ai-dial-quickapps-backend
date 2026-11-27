import pytest
from pydantic import ValidationError

from quickapp.common.synthetic_injection.injection_enums import InjectionFrequency
from quickapp.config.application import ApplicationConfig
from quickapp.config.hooks import (
    HookConfig,
    HookEvent,
    HookExecution,
    ToolCallHookConfig,
    TTLRefreshCondition,
)
from tests.unit_tests.common.common import create_app_configuration


class TestToolCallHookConfig:
    def test_minimal_construction(self):
        cfg = ToolCallHookConfig(event=HookEvent.ON_REQUEST_START, tool_name="my_tool")
        assert cfg.event == HookEvent.ON_REQUEST_START
        assert cfg.tool_name == "my_tool"
        assert cfg.toolset_name is None
        assert cfg.arguments == {}
        assert cfg.frequency == InjectionFrequency.APPEND_IF_CHANGED
        assert cfg.name is None
        assert cfg.kind == "tool_call"

    def test_full_construction(self):
        cfg = ToolCallHookConfig(
            event=HookEvent.ON_REQUEST_START,
            name="my hook",
            toolset_name="memory_server",
            tool_name="get_memories",
            arguments={"user_id": "current"},
            frequency=InjectionFrequency.ALWAYS,
        )
        assert cfg.toolset_name == "memory_server"
        assert cfg.tool_name == "get_memories"
        assert cfg.arguments == {"user_id": "current"}
        assert cfg.frequency == InjectionFrequency.ALWAYS
        assert cfg.name == "my hook"

    def test_tool_name_required(self):
        with pytest.raises(ValidationError):
            ToolCallHookConfig(event=HookEvent.ON_REQUEST_START)

    def test_parses_from_dict(self):
        data = {
            "kind": "tool_call",
            "event": "on_request_start",
            "tool_name": "fetch_prefs",
            "frequency": "always",
        }
        cfg = ToolCallHookConfig.model_validate(data)
        assert cfg.tool_name == "fetch_prefs"
        assert cfg.frequency == InjectionFrequency.ALWAYS

    def test_refresh_condition_defaults_to_none(self):
        cfg = ToolCallHookConfig(event=HookEvent.ON_REQUEST_START, tool_name="my_tool")
        assert cfg.refresh_condition is None

    def test_refresh_condition_accepts_ttl(self):
        rc = TTLRefreshCondition(ttl_minutes=30)
        cfg = ToolCallHookConfig(
            event=HookEvent.ON_REQUEST_START, tool_name="my_tool", refresh_condition=rc
        )
        assert isinstance(cfg.refresh_condition, TTLRefreshCondition)
        assert cfg.refresh_condition.ttl_minutes == 30

    def test_refresh_condition_parses_ttl_from_dict(self):
        data = {
            "kind": "tool_call",
            "event": "on_request_start",
            "tool_name": "fetch_memories",
            "refresh_condition": {"kind": "ttl", "ttl_minutes": 1440},
        }
        cfg = ToolCallHookConfig.model_validate(data)
        assert isinstance(cfg.refresh_condition, TTLRefreshCondition)
        assert cfg.refresh_condition.ttl_minutes == 1440

    def test_hook_config_parses_tool_call_variant(self):
        data = {
            "kind": "tool_call",
            "event": "on_request_start",
            "tool_name": "my_tool",
        }
        cfg = HookConfig.model_validate(data)
        assert isinstance(cfg, ToolCallHookConfig)
        assert cfg.tool_name == "my_tool"

    def test_execution_defaults_to_blocking(self):
        cfg = ToolCallHookConfig(event=HookEvent.ON_COMPLETION, tool_name="t")
        assert cfg.execution is HookExecution.BLOCKING
        assert cfg.model_dump()["execution"] == "blocking"

    def test_execution_background_parses_from_dict(self):
        cfg = ToolCallHookConfig.model_validate(
            {"event": "on_completion", "tool_name": "t", "execution": "background"}
        )
        assert cfg.execution is HookExecution.BACKGROUND

    def test_execution_rejects_unknown_value(self):
        with pytest.raises(ValidationError, match="execution"):
            ToolCallHookConfig.model_validate(
                {"event": "on_completion", "tool_name": "t", "execution": "async"}
            )

    def test_background_rejected_for_request_start(self):
        with pytest.raises(ValidationError, match="only supported for event 'on_completion'"):
            ToolCallHookConfig.model_validate(
                {"event": "on_request_start", "tool_name": "t", "execution": "background"}
            )

    def test_blocking_is_accepted_for_request_start(self):
        # A dumped config always carries the default, so it must validate again.
        cfg = ToolCallHookConfig.model_validate(
            {"event": "on_request_start", "tool_name": "t", "execution": "blocking"}
        )
        assert cfg.execution is HookExecution.BLOCKING


class TestApplicationConfigHooksField:
    def test_hooks_field_exists_and_defaults_to_none(self):
        config = create_app_configuration([])
        assert config.hooks is None

    def test_hooks_field_preserved_when_preview_disabled(self, monkeypatch):
        monkeypatch.delenv("ENABLE_PREVIEW_FEATURES", raising=False)
        hook = ToolCallHookConfig(event=HookEvent.ON_REQUEST_START, tool_name="my_tool")
        data = create_app_configuration([]).model_dump(mode="json")
        data["hooks"] = [hook.model_dump(mode="json")]
        config = ApplicationConfig.model_validate(data)
        assert config.hooks is not None
        assert len(config.hooks) == 1
        assert config.hooks[0].tool_name == "my_tool"
