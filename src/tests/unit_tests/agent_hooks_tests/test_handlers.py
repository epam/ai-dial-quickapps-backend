import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from quickapp.agent_hooks._handlers import (
    HookHandlerRegistry,
    ToolCallHookHandler,
    hook_display_name,
    resolve_hook_tool_name,
)
from quickapp.common.hook_context.context import HookMessage, RequestStartHookContext
from quickapp.common.staged_base_tool import StagedBaseTool
from quickapp.config.application import StageDisplayLevel
from quickapp.config.hooks import ToolCallHookConfig
from tests.unit_tests.common.common import make_provider


def _tool(function_name: str, content: str = "tool-output") -> MagicMock:
    tool = MagicMock(spec=StagedBaseTool)
    tool.tool_config = SimpleNamespace(
        open_ai_tool=SimpleNamespace(function=SimpleNamespace(name=function_name))
    )
    tool.arun = AsyncMock(return_value=SimpleNamespace(content=content))
    return tool


def _config(**overrides: object) -> ToolCallHookConfig:
    data: dict[str, object] = {"event": "on_request_start", "tool_name": "search"}
    data.update(overrides)
    return ToolCallHookConfig(**data)  # type: ignore[arg-type]


def _context(*messages: HookMessage) -> RequestStartHookContext:
    return RequestStartHookContext(event="on_request_start", messages=list(messages))


_USER_CONTEXT = _context(HookMessage(role="user", content="find cats"))


class TestNames:
    def test_resolve_without_toolset_uses_tool_name_verbatim(self) -> None:
        assert resolve_hook_tool_name(_config(tool_name="My_Tool")) == "My_Tool"

    def test_resolve_with_toolset_is_sanitized_prefix(self) -> None:
        config = _config(toolset_name="memory_server", tool_name="get")
        assert resolve_hook_tool_name(config) == "memory_server_get"

    def test_display_name_prefers_name(self) -> None:
        assert hook_display_name(_config(name="my hook")) == "my hook"
        assert hook_display_name(_config()) == "search"


class TestToolCallHookHandler:
    @pytest.mark.asyncio
    async def test_renders_arguments_and_calls_tool(self) -> None:
        tool = _tool("search")
        handler = ToolCallHookHandler(
            _config(name="h", arguments={"query": "${last_user_message.content}", "limit": 3}),
            [tool],
        )

        result = await handler.run(_USER_CONTEXT)

        tool.arun.assert_awaited_once_with(
            "synthetic_injection_probe",
            stage_level=StageDisplayLevel.DEBUG,
            query="find cats",
            limit=3,
        )
        assert result is not None
        assert result.hook_name == "h"
        assert result.content == "tool-output"
        assert result.tool_name == "search"
        assert result.arguments == {"query": "find cats", "limit": 3}

    @pytest.mark.asyncio
    async def test_literal_arguments_pass_through_unchanged(self) -> None:
        tool = _tool("search")
        handler = ToolCallHookHandler(_config(arguments={"user_id": "current"}), [tool])

        result = await handler.run(_USER_CONTEXT)

        assert tool.arun.await_args.kwargs["user_id"] == "current"
        assert result is not None
        assert result.arguments == {"user_id": "current"}

    @pytest.mark.asyncio
    async def test_unresolvable_template_skips_hook_without_calling_tool(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        tool = _tool("search")
        handler = ToolCallHookHandler(
            _config(name="h", arguments={"q": {"$eval": "last_assistant_message.content"}}),
            [tool],
        )

        with caplog.at_level(logging.WARNING):
            result = await handler.run(_USER_CONTEXT)

        assert result is None
        tool.arun.assert_not_awaited()
        assert "template.q" in caplog.text
        assert "find cats" not in caplog.text

    @pytest.mark.asyncio
    async def test_missing_tool_returns_none(self) -> None:
        handler = ToolCallHookHandler(_config(tool_name="absent"), [_tool("other")])
        assert await handler.run(_USER_CONTEXT) is None

    @pytest.mark.asyncio
    async def test_tool_exception_propagates(self) -> None:
        tool = _tool("search")
        tool.arun.side_effect = RuntimeError("boom")
        handler = ToolCallHookHandler(_config(), [tool])

        with pytest.raises(RuntimeError, match="boom"):
            await handler.run(_USER_CONTEXT)

    @pytest.mark.asyncio
    async def test_toolset_name_is_applied_to_lookup(self) -> None:
        tool = _tool("memory_server_get")
        handler = ToolCallHookHandler(
            _config(toolset_name="memory_server", tool_name="get"), [tool]
        )

        result = await handler.run(_USER_CONTEXT)

        assert result is not None
        assert result.tool_name == "memory_server_get"
        tool.arun.assert_awaited_once()


class TestHookHandlerRegistry:
    def test_builds_tool_call_handler(self) -> None:
        registry = HookHandlerRegistry(make_provider([_tool("search")]))
        assert isinstance(registry.handler_for(_config()), ToolCallHookHandler)

    def test_caches_handler_per_hook_instance(self) -> None:
        provider = make_provider([_tool("search")])
        registry = HookHandlerRegistry(provider)
        hook = _config()

        assert registry.handler_for(hook) is registry.handler_for(hook)
        provider.get.assert_called_once()

    def test_distinct_hooks_get_distinct_handlers(self) -> None:
        registry = HookHandlerRegistry(make_provider([_tool("search")]))
        assert registry.handler_for(_config()) is not registry.handler_for(_config())
