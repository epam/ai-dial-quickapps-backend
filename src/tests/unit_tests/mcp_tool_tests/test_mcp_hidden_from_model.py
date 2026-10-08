import logging
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import SecretStr

from quickapp.config.toolsets.dial_mcp import DialMCPToolSet
from quickapp.config.toolsets.mcp import MCPProtocol, MCPServerInfo, MCPToolSet

# noinspection PyProtectedMember
from quickapp.mcp_tooling._mcp_tool_initializer import _MCPToolInitializer
from tests.unit_tests.common.common import make_access_filter, make_provider


def _server_tool(name: str) -> MagicMock:
    tool = MagicMock()
    tool.name = name
    tool.description = f"{name} description"
    tool.inputSchema = {"type": "object", "properties": {}}
    return tool


def _toolset_client(*tool_names: str) -> MagicMock:
    client = MagicMock()
    client.get_tools_list = AsyncMock(return_value=[_server_tool(n) for n in tool_names])
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


def _tool_builder() -> MagicMock:
    def _build(tool, **_kwargs):
        built = MagicMock()
        built.server_tool_name = tool.name
        return built

    builder = MagicMock()
    builder.build.side_effect = _build
    return builder


def _initializer(
    toolsets: list[MCPToolSet | DialMCPToolSet],
    client: MagicMock,
    *,
    discovery_enabled: bool = False,
    dial_mcp_cache: MagicMock | None = None,
) -> tuple[_MCPToolInitializer, MagicMock, MagicMock]:
    mcp_context = MagicMock()
    client_builder = MagicMock()
    client_builder.build.return_value = client
    app_config = MagicMock()
    app_config.orchestrator.tool_discovery.enabled = discovery_enabled
    app_config.orchestrator.tool_discovery.min_tools_for_deferral = 1
    dial_setting = MagicMock(url="https://dial.example")
    initializer = _MCPToolInitializer(
        make_provider(toolsets),
        mcp_context,
        dial_setting,
        make_provider(SecretStr("api-key")),
        _tool_builder(),
        client_builder,
        dial_mcp_cache or MagicMock(),
        MagicMock(),
        MagicMock(),
        None,
        app_config,
        make_access_filter(),
    )
    return initializer, mcp_context, client_builder


def _mcp_toolset(**kwargs: object) -> MCPToolSet:
    return MCPToolSet(
        name="memory",
        mcp_server_info=MCPServerInfo(
            url="https://srv", authorization=None, protocol=MCPProtocol.streamable_http
        ),
        **kwargs,  # type: ignore[arg-type]
    )


def _names(call_args: tuple) -> list[str]:
    return [t.server_tool_name for t in call_args[0][0]]


@pytest.mark.asyncio
async def test_listed_tools_go_to_model_hidden_bucket_and_rest_stay_visible() -> None:
    toolset = _mcp_toolset(hidden_from_model=["get_skill", "save_memory"])
    initializer, ctx, _ = _initializer(
        [toolset], _toolset_client("get_skill", "save_memory", "search_memories")
    )

    await initializer.initialize()

    assert _names(ctx.extend_model_hidden_tools.call_args) == ["get_skill", "save_memory"]
    assert _names(ctx.extend_tools.call_args) == ["search_memories"]


@pytest.mark.asyncio
async def test_no_hidden_from_model_keeps_every_tool_visible() -> None:
    initializer, ctx, _ = _initializer([_mcp_toolset()], _toolset_client("a", "b"))

    await initializer.initialize()

    ctx.extend_model_hidden_tools.assert_not_called()
    assert _names(ctx.extend_tools.call_args) == ["a", "b"]


@pytest.mark.asyncio
async def test_all_tools_hidden_registers_nothing_visible_or_deferred() -> None:
    toolset = _mcp_toolset(hidden_from_model=["a", "b"], deferred=True)
    initializer, ctx, _ = _initializer([toolset], _toolset_client("a", "b"), discovery_enabled=True)

    await initializer.initialize()

    assert _names(ctx.extend_model_hidden_tools.call_args) == ["a", "b"]
    ctx.extend_tools.assert_not_called()
    ctx.register_deferred_tools.assert_not_called()


@pytest.mark.asyncio
async def test_deferral_sees_only_model_visible_tools() -> None:
    toolset = _mcp_toolset(hidden_from_model=["a"], deferred=True)
    initializer, ctx, _ = _initializer([toolset], _toolset_client("a", "b"), discovery_enabled=True)

    await initializer.initialize()

    ctx.register_deferred_tools.assert_called_once()
    deferred = ctx.register_deferred_tools.call_args[0][1]
    assert [t.server_tool_name for t in deferred] == ["b"]


@pytest.mark.asyncio
async def test_unknown_hidden_name_is_warned_not_failed(caplog: pytest.LogCaptureFixture) -> None:
    toolset = _mcp_toolset(hidden_from_model=["a", "typo"])
    initializer, ctx, _ = _initializer([toolset], _toolset_client("a", "b"))

    with caplog.at_level(logging.WARNING):
        await initializer.initialize()

    assert "typo" in caplog.text
    assert _names(ctx.extend_model_hidden_tools.call_args) == ["a"]
    ctx.append_exception.assert_not_called()


@pytest.mark.asyncio
async def test_dial_mcp_toolset_resolution_carries_hidden_from_model() -> None:
    toolset = DialMCPToolSet(
        name="memory",
        deployment_id="toolsets/memory",
        allowed_tools=["a", "b"],
        hidden_from_model=["a"],
    )
    dial_info = MagicMock(display_name="Memory", description="d", transport="http")
    cache = MagicMock()
    cache.get = AsyncMock(return_value=dial_info)
    initializer, ctx, client_builder = _initializer(
        [toolset], _toolset_client("a", "b"), dial_mcp_cache=cache
    )

    await initializer.initialize()

    resolved = client_builder.build.call_args.kwargs["toolset_info"]
    assert resolved.hidden_from_model == ["a"]
    assert _names(ctx.extend_model_hidden_tools.call_args) == ["a"]
    assert _names(ctx.extend_tools.call_args) == ["b"]
