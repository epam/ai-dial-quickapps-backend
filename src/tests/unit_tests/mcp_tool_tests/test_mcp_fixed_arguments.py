import logging
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import SecretStr

from quickapp.common.dial_settings import DialSettings
from quickapp.common.exceptions import ToolInitializationException
from quickapp.common.perf_timer.perf_timer import PerformanceTimer
from quickapp.common.state_holder import StateHolder
from quickapp.config.tools.base import (
    ConfigurableSchemaSimpleType,
    JsonTypeEnum,
    OpenAiToolConfig,
    OpenAiToolFunction,
    OpenAiToolFunctionParameters,
)
from quickapp.config.tools.mcp import MCPTool
from quickapp.config.toolsets.dial_mcp import DialMCPToolSet
from quickapp.config.toolsets.mcp import MCPProtocol, MCPServerInfo, MCPToolSet
from quickapp.dial_core_services.attachment_service import AttachmentService
from quickapp.dial_core_services.dial_file_service import DialFileService

# noinspection PyProtectedMember
from quickapp.mcp_tooling._mcp_stage_wrapper import _MCPStageWrapper

# noinspection PyProtectedMember
from quickapp.mcp_tooling._mcp_tool import _MCPTool

# noinspection PyProtectedMember
from quickapp.mcp_tooling._mcp_tool_initializer import _MCPToolInitializer

# noinspection PyProtectedMember
from quickapp.mcp_tooling._mcp_toolset_client import _MCPToolsetClient
from tests.unit_tests.common.common import make_access_filter, make_provider, noop_timeout_resolver

_SEARCH_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "Search text"},
        "project_key": {"type": "string", "description": "Jira project"},
    },
    "required": ["query", "project_key"],
}


def _server_tool(name: str, input_schema: dict[str, Any]) -> MagicMock:
    tool = MagicMock()
    tool.name = name
    tool.description = f"{name} description"
    tool.inputSchema = input_schema
    return tool


def _toolset_client(input_schema: dict[str, Any], *tool_names: str) -> MagicMock:
    client = MagicMock()
    client.get_tools_list = AsyncMock(
        return_value=[_server_tool(n, input_schema) for n in tool_names]
    )
    init_result = MagicMock()
    init_result.serverInfo.name = "srv"
    init_result.serverInfo.version = "1.0"
    init_result.protocolVersion = "2025-03-26"
    init_result.capabilities.resources = None
    init_result.capabilities.prompts = None

    @asynccontextmanager
    async def _open():
        yield MagicMock(), init_result

    client.open_init_session = _open
    return client


def _initializer(
    toolsets: list[MCPToolSet | DialMCPToolSet],
    client: MagicMock,
    dial_mcp_cache: MagicMock | None = None,
) -> tuple[_MCPToolInitializer, MagicMock, MagicMock, MagicMock]:
    mcp_context = MagicMock()
    client_builder = MagicMock()
    client_builder.build.return_value = client
    tool_builder = MagicMock()
    app_config = MagicMock()
    app_config.orchestrator.tool_discovery.enabled = False
    initializer = _MCPToolInitializer(
        make_provider(toolsets),
        mcp_context,
        MagicMock(url="https://dial.example"),
        make_provider(SecretStr("api-key")),
        tool_builder,
        client_builder,
        dial_mcp_cache or MagicMock(),
        MagicMock(),
        MagicMock(),
        None,
        app_config,
        make_access_filter(),
    )
    return initializer, mcp_context, client_builder, tool_builder


def _mcp_toolset(**kwargs: object) -> MCPToolSet:
    return MCPToolSet(
        name="jira",
        mcp_server_info=MCPServerInfo(
            url="https://srv", authorization=None, protocol=MCPProtocol.streamable_http
        ),
        **kwargs,  # type: ignore[arg-type]
    )


def _build_kwargs(tool_builder: MagicMock, server_tool_name: str) -> dict[str, Any]:
    for call in tool_builder.build.call_args_list:
        if call.kwargs["tool"].name == server_tool_name:
            return call.kwargs
    raise AssertionError(f"tool {server_tool_name} was not built")


def _built_open_ai_tool(tool_builder: MagicMock, server_tool_name: str) -> OpenAiToolConfig:
    return _build_kwargs(tool_builder, server_tool_name)["tool_config"].open_ai_tool


class TestInitializer:
    @pytest.mark.asyncio
    async def test_fixed_argument_is_removed_from_schema_and_passed_to_tool(self) -> None:
        toolset = _mcp_toolset(fixed_arguments={"search": {"project_key": "DIAL"}})
        initializer, ctx, _, tool_builder = _initializer(
            [toolset], _toolset_client(_SEARCH_SCHEMA, "search")
        )

        await initializer.initialize()

        build_kwargs = _build_kwargs(tool_builder, "search")
        visible = build_kwargs["tool_config"].open_ai_tool.function.parameters
        assert list(visible.properties) == ["query"]
        assert visible.required == ["query"]
        assert build_kwargs["fixed_arguments"] == {"project_key": "DIAL"}
        ctx.append_exception.assert_not_called()

    @pytest.mark.asyncio
    async def test_other_tools_are_untouched(self) -> None:
        toolset = _mcp_toolset(fixed_arguments={"search": {"project_key": "DIAL"}})
        initializer, _, _, tool_builder = _initializer(
            [toolset], _toolset_client(_SEARCH_SCHEMA, "search", "create")
        )

        await initializer.initialize()

        build_kwargs = _build_kwargs(tool_builder, "create")
        assert (
            "project_key" in build_kwargs["tool_config"].open_ai_tool.function.parameters.properties
        )
        assert build_kwargs["fixed_arguments"] is None

    @pytest.mark.asyncio
    async def test_unknown_argument_is_reported_and_tool_kept(self) -> None:
        toolset = _mcp_toolset(fixed_arguments={"search": {"projectKey": "DIAL"}})
        initializer, ctx, _, tool_builder = _initializer(
            [toolset], _toolset_client(_SEARCH_SCHEMA, "search")
        )

        await initializer.initialize()

        ctx.append_exception.assert_called_once()
        error = ctx.append_exception.call_args[0][0]
        assert isinstance(error, ToolInitializationException)
        assert "projectKey" in error.message
        assert error.tool_name == "search"
        assert _build_kwargs(tool_builder, "search")["fixed_arguments"] == {"projectKey": "DIAL"}

    @pytest.mark.asyncio
    async def test_unknown_argument_allowed_by_additional_properties(self) -> None:
        schema = {**_SEARCH_SCHEMA, "additionalProperties": True}
        toolset = _mcp_toolset(fixed_arguments={"search": {"extra": 1}})
        initializer, ctx, _, _ = _initializer([toolset], _toolset_client(schema, "search"))

        await initializer.initialize()

        ctx.append_exception.assert_not_called()

    @pytest.mark.asyncio
    async def test_unknown_tool_is_warned_not_failed(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        toolset = _mcp_toolset(fixed_arguments={"typo": {"project_key": "DIAL"}})
        initializer, ctx, _, _ = _initializer([toolset], _toolset_client(_SEARCH_SCHEMA, "search"))

        with caplog.at_level(logging.WARNING):
            await initializer.initialize()

        assert "fixed_arguments" in caplog.text
        assert "typo" in caplog.text
        ctx.append_exception.assert_not_called()

    @pytest.mark.asyncio
    async def test_dial_mcp_toolset_resolution_carries_fixed_arguments(self) -> None:
        toolset = DialMCPToolSet(
            name="jira",
            deployment_id="toolsets/jira",
            fixed_arguments={"search": {"project_key": "DIAL"}},
        )
        cache = MagicMock()
        cache.get = AsyncMock(
            return_value=MagicMock(display_name="Jira", description="d", transport="http")
        )
        initializer, _, client_builder, tool_builder = _initializer(
            [toolset], _toolset_client(_SEARCH_SCHEMA, "search"), dial_mcp_cache=cache
        )

        await initializer.initialize()

        resolved = client_builder.build.call_args.kwargs["toolset_info"]
        assert resolved.fixed_arguments == {"search": {"project_key": "DIAL"}}
        props = _built_open_ai_tool(tool_builder, "search").function.parameters.properties
        assert "project_key" not in props


def _tool_config() -> MCPTool:
    properties: dict[str, Any] = {
        "query": ConfigurableSchemaSimpleType(type=JsonTypeEnum.string),
    }
    return MCPTool(
        open_ai_tool=OpenAiToolConfig(
            function=OpenAiToolFunction(
                name="jira_search",
                description="search",
                parameters=OpenAiToolFunctionParameters(
                    type=JsonTypeEnum.object, properties=properties
                ),
            )
        )
    )


def _make_tool(
    fixed_arguments: dict[str, Any] | None, transformer: MagicMock | None = None
) -> _MCPTool:
    dial_settings = MagicMock(spec=DialSettings)
    dial_settings.url = "https://dial.example.com"
    file_service = MagicMock(spec=DialFileService)
    file_service.grant_permissions_to_files = AsyncMock()
    stage_wrapper_builder = MagicMock()
    stage_wrapper_builder.build.return_value = MagicMock(spec=_MCPStageWrapper)
    return _MCPTool(
        tool=SimpleNamespace(name="search", description="search", inputSchema={}),
        tool_config=_tool_config(),
        toolset_client=MagicMock(spec=_MCPToolsetClient),
        stage_wrapper_builder=stage_wrapper_builder,
        state_holder=StateHolder(),
        dial_attachment_service=MagicMock(spec=AttachmentService),
        perf_timer=PerformanceTimer(),
        file_service=file_service,
        dial_toolset_id=None,
        login_service=MagicMock(),
        timeout_resolver=noop_timeout_resolver(),
        dial_settings=dial_settings,
        argument_transformers=[transformer] if transformer else None,
        fixed_arguments=fixed_arguments,
    )


class TestToolCall:
    @pytest.mark.asyncio
    async def test_fixed_value_is_added_and_overrides_caller(self) -> None:
        tool = _make_tool({"project_key": "DIAL", "limit": 50})

        params = await tool._pre_process_params(query="bug", project_key="OTHER")

        assert params == {"query": "bug", "project_key": "DIAL", "limit": 50}

    @pytest.mark.asyncio
    async def test_transformers_see_fixed_values(self) -> None:
        transformer = MagicMock()
        transformer.transform = AsyncMock(side_effect=lambda kwargs: kwargs)
        tool = _make_tool({"project_key": "DIAL"}, transformer)

        await tool._pre_process_params(query="bug")

        transformer.transform.assert_awaited_once_with({"query": "bug", "project_key": "DIAL"})

    def test_stage_parameters_drop_fixed_values(self) -> None:
        tool = _make_tool({"project_key": "DIAL"})

        shown = tool._stage_parameters({"query": "bug", "project_key": "DIAL"})

        assert shown == {"query": "bug"}

    @pytest.mark.asyncio
    async def test_no_fixed_arguments_keeps_params(self) -> None:
        tool = _make_tool(None)

        assert await tool._pre_process_params(query="bug") == {"query": "bug"}
        assert tool._stage_parameters({"query": "bug"}) == {"query": "bug"}
