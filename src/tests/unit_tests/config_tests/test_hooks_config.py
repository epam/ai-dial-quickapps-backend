import pytest
from pydantic import ValidationError

from quickapp.common.synthetic_injection.injection_enums import InjectionFrequency
from quickapp.config.hooks import HookConfig, HookEvent, ToolCallHookConfig, TTLRefreshCondition
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


class TestApplicationConfigHooksField:
    def test_hooks_field_exists_and_defaults_to_none(self, monkeypatch):
        monkeypatch.setenv("ENABLE_PREVIEW_FEATURES", "true")
        config = create_app_configuration([])
        assert config.hooks is None

    def test_hooks_field_nullified_when_preview_disabled(self, monkeypatch):
        monkeypatch.delenv("ENABLE_PREVIEW_FEATURES", raising=False)
        config = create_app_configuration([])
        assert config.hooks is None

    def test_hooks_field_preserved_when_supplied_with_preview_enabled(self, monkeypatch):
        monkeypatch.setenv("ENABLE_PREVIEW_FEATURES", "true")
        hook = ToolCallHookConfig(event=HookEvent.ON_REQUEST_START, tool_name="my_tool")
        config = create_app_configuration([])
        config.hooks = [hook]
        assert config.hooks is not None
        assert len(config.hooks) == 1
        assert config.hooks[0].tool_name == "my_tool"
