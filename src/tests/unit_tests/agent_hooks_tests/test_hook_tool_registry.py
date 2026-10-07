from types import SimpleNamespace
from unittest.mock import MagicMock

from quickapp.agent_hooks._agent_hooks_context import _AgentHooksContext
from quickapp.agent_hooks._hook_tool_registry import HookToolRegistry
from quickapp.common.exceptions import HookInitializationException
from quickapp.config.hooks import ToolCallHookConfig
from tests.unit_tests.common.common import make_provider


def _tool(function_name: str) -> MagicMock:
    tool = MagicMock()
    tool.tool_config = SimpleNamespace(
        open_ai_tool=SimpleNamespace(function=SimpleNamespace(name=function_name))
    )
    return tool


def _hook(toolset_name: str, tool_name: str) -> ToolCallHookConfig:
    return ToolCallHookConfig(
        event="on_request_start", toolset_name=toolset_name, tool_name=tool_name
    )


def test_registry_returns_visible_then_model_hidden_tools() -> None:
    visible, hidden = _tool("memory_search"), _tool("memory_save")
    registry = HookToolRegistry(make_provider([visible]), make_provider([hidden]))

    assert registry.tools == [visible, hidden]


def test_hook_validation_accepts_model_hidden_tool() -> None:
    registry = HookToolRegistry(make_provider([]), make_provider([_tool("memory_save")]))
    config = SimpleNamespace(hooks=[_hook("memory", "save")])

    context = _AgentHooksContext(make_provider(config), registry)

    assert context.exceptions == []


def test_hook_validation_still_reports_missing_tool() -> None:
    registry = HookToolRegistry(make_provider([]), make_provider([_tool("memory_save")]))
    config = SimpleNamespace(hooks=[_hook("memory", "typo")])

    exceptions = _AgentHooksContext(make_provider(config), registry).exceptions

    assert len(exceptions) == 1
    assert isinstance(exceptions[0], HookInitializationException)
    assert "memory_typo" in exceptions[0].message
