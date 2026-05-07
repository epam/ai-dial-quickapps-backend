from unittest.mock import MagicMock

from quickapp.agent_hooks._config_driven_hooks import _ConfigDrivenToolCallHook
from quickapp.agent_hooks.agent_hooks_module import AgentHooksModule
from quickapp.common.synthetic_injection.injection_enums import InjectionFrequency
from quickapp.config.application import ApplicationConfig
from quickapp.config.hooks import HookEvent, ToolCallHookConfig


def _make_app_config(hooks) -> MagicMock:
    config = MagicMock(spec=ApplicationConfig)
    config.hooks = hooks
    return config


class TestAgentHooksModuleBuild:
    def test_returns_empty_list_when_hooks_is_none(self):
        module = AgentHooksModule()
        config = _make_app_config(None)
        result = module._build(config, [], HookEvent.ON_REQUEST_START)
        assert result == []

    def test_returns_empty_list_when_hooks_is_empty(self):
        module = AgentHooksModule()
        config = _make_app_config([])
        result = module._build(config, [], HookEvent.ON_REQUEST_START)
        assert result == []

    def test_skips_hooks_for_different_event(self):
        module = AgentHooksModule()
        hook_cfg = ToolCallHookConfig(event=HookEvent.ON_PRE_LLM, tool_name="tool")
        config = _make_app_config([hook_cfg])
        result = module._build(config, [], HookEvent.ON_REQUEST_START)
        assert result == []

    def test_returns_hook_for_matching_on_request_start(self):
        module = AgentHooksModule()
        hook_cfg = ToolCallHookConfig(event=HookEvent.ON_REQUEST_START, tool_name="my_tool")
        config = _make_app_config([hook_cfg])
        result = module._build(config, [], HookEvent.ON_REQUEST_START)
        assert len(result) == 1
        assert isinstance(result[0], _ConfigDrivenToolCallHook)

    def test_returns_multiple_hooks_for_same_event(self):
        module = AgentHooksModule()
        cfg_a = ToolCallHookConfig(event=HookEvent.ON_REQUEST_START, tool_name="tool_a")
        cfg_b = ToolCallHookConfig(event=HookEvent.ON_REQUEST_START, tool_name="tool_b")
        cfg_c = ToolCallHookConfig(event=HookEvent.ON_PRE_LLM, tool_name="tool_c")
        config = _make_app_config([cfg_a, cfg_b, cfg_c])
        result = module._build(config, [], HookEvent.ON_REQUEST_START)
        assert len(result) == 2
        assert all(isinstance(h, _ConfigDrivenToolCallHook) for h in result)

    def test_hook_has_correct_config(self):
        module = AgentHooksModule()
        hook_cfg = ToolCallHookConfig(
            event=HookEvent.ON_REQUEST_START,
            tool_name="mem_tool",
            toolset_name="memory_server",
            frequency=InjectionFrequency.ALWAYS,
        )
        config = _make_app_config([hook_cfg])
        result = module._build(config, [], HookEvent.ON_REQUEST_START)
        hook = result[0]
        assert isinstance(hook, _ConfigDrivenToolCallHook)
        assert hook._config is hook_cfg


class TestAgentHooksModuleProvideMessagesTransformers:
    def test_logs_error_for_unsupported_event(self, caplog):
        import logging

        module = AgentHooksModule()
        hook_cfg = ToolCallHookConfig(event=HookEvent.ON_PRE_LLM, tool_name="tool")
        config = _make_app_config([hook_cfg])
        with caplog.at_level(logging.ERROR):
            module._provide_messages_transformers(config, [])
        assert any("not yet supported" in r.message for r in caplog.records)


class TestAgentHooksModuleIsPreview:
    def test_module_is_marked_as_preview(self):
        from quickapp.common.preview import is_preview_module

        assert is_preview_module(AgentHooksModule())
