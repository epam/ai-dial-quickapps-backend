"""Tests for multi-phase interactive login in _MCPToolInitializer.initialize()."""

from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
from aidial_client import ToolsetInfo
from aidial_client.types.deployment import Features
from pydantic import SecretStr

from quickapp.common.exceptions import ToolInitializationException
from quickapp.config.toolsets.dial_mcp import DialMCPToolSet
from quickapp.config.toolsets.mcp import MCPProtocol, MCPServerInfo, MCPToolSet
from quickapp.dial_core_services._login_result import LoginResult
from quickapp.mcp_tooling._mcp_tool import _MCPTool
from quickapp.mcp_tooling._mcp_tool_initializer import _MCPToolInitializer
from quickapp.mcp_tooling._mcp_unauthorized_exception import MCPUnauthorizedException
from tests.unit_tests.common.common import noop_timeout_resolver


def _make_dial_toolset(dial_id: str = "toolsets/public/ts1", name: str = "ts1") -> DialMCPToolSet:
    return DialMCPToolSet(
        dial_id=dial_id,
        name=name,
        enabled=True,
    )


def _make_mcp_toolset(name: str = "ext-toolset") -> MCPToolSet:
    return MCPToolSet(
        mcp_server_info=MCPServerInfo(
            url="https://ext-mcp", authorization=None, protocol=MCPProtocol.sse
        ),
        name=name,
    )


def _build_tool_side_effect(tool, tool_config, connection_manager=None, **kwargs):
    return _MCPTool(
        tool=tool,
        tool_config=tool_config,
        connection_manager=connection_manager,
        stage_wrapper_builder=MagicMock(),
        dial_attachment_service=MagicMock(),
        state_holder=MagicMock(),
        perf_timer=Mock(),
        file_service=MagicMock(),
        dial_toolset_id=None,
        login_service=MagicMock(),
        timeout_resolver=noop_timeout_resolver(),
    )


def _make_toolset_info() -> ToolsetInfo:
    """Create a minimal ToolsetInfo for DialMCPToolSet resolution."""
    return ToolsetInfo(
        id="ts1",
        toolset="toolsets/public/ts1",
        display_name="ts1",
        description="test",
        features=Features(),
        transport="HTTP",
    )


def _make_initializer(
    toolset_list,
    login_service=None,
    connection_manager_builder=None,
):
    mcp_context = MagicMock()

    if connection_manager_builder is None:
        conn = MagicMock()
        conn.get_tools_list = AsyncMock(return_value=[])
        connection_manager_builder = MagicMock()
        connection_manager_builder.build.return_value = conn

    tool_builder = MagicMock()
    tool_builder.build.side_effect = _build_tool_side_effect

    if login_service is None:
        login_service = AsyncMock()
        login_service.request_signin_batch = AsyncMock(return_value={})

    # api_key_provider must return a SecretStr for DialMCPToolSet resolution
    api_key_provider = MagicMock()
    api_key_provider.get.return_value = SecretStr("test-key")

    # dial_mcp_cache must be an AsyncMock since .get() is awaited
    dial_mcp_cache = AsyncMock()
    dial_mcp_cache.get = AsyncMock(return_value=_make_toolset_info())

    dial_setting = MagicMock()
    dial_setting.url = "http://dial-core"

    dial_app_resolver = MagicMock()
    dial_app_resolver.resolve = AsyncMock()
    dial_app_resolver_context = MagicMock()
    dial_app_resolver_context.resolved_mcp_toolsets = []

    initializer = _MCPToolInitializer(
        toolset_list=toolset_list,
        mcp_context=mcp_context,
        dial_setting=dial_setting,
        api_key_provider=api_key_provider,
        tool_builder=tool_builder,
        connection_manager_builder=connection_manager_builder,
        dial_mcp_cache=dial_mcp_cache,
        tool_config_service=MagicMock(),
        login_service=login_service,
        dial_app_resolver=dial_app_resolver,
        dial_app_resolver_context=dial_app_resolver_context,
    )
    return initializer, mcp_context, login_service


@pytest.mark.asyncio
async def test_no_401_no_login_called():
    """When no toolsets return 401, interactive login is never called."""
    ts = _make_mcp_toolset()
    conn = MagicMock()
    conn.get_tools_list = AsyncMock(return_value=[])
    conn_builder = MagicMock()
    conn_builder.build.return_value = conn

    initializer, mcp_context, login_service = _make_initializer(
        [ts], connection_manager_builder=conn_builder
    )
    await initializer.initialize()

    login_service.request_signin_batch.assert_not_awaited()
    mcp_context.append_exception.assert_not_called()


@pytest.mark.asyncio
async def test_dial_toolset_401_triggers_batch_login():
    """DialMCPToolSet returning 401 triggers batch interactive login."""
    ts = _make_dial_toolset(dial_id="toolsets/public/ts1")

    conn = MagicMock()
    conn.get_tools_list = AsyncMock(side_effect=MCPUnauthorizedException("ts1"))
    conn_builder = MagicMock()
    conn_builder.build.return_value = conn

    login_service = AsyncMock()
    login_service.request_signin_batch = AsyncMock(
        return_value={"toolsets/public/ts1": LoginResult.DENIED}
    )

    initializer, mcp_context, _ = _make_initializer(
        [ts], login_service=login_service, connection_manager_builder=conn_builder
    )
    await initializer.initialize()

    login_service.request_signin_batch.assert_awaited_once_with(["toolsets/public/ts1"])
    assert mcp_context.append_exception.call_count == 1
    exc = mcp_context.append_exception.call_args[0][0]
    assert isinstance(exc, ToolInitializationException)
    assert "denied" in exc.message.lower()


@pytest.mark.asyncio
async def test_dial_toolset_401_success_retries():
    """DialMCPToolSet 401 → login SUCCESS → retry succeeds."""
    ts = _make_dial_toolset(dial_id="toolsets/public/ts1")

    call_count = 0

    async def get_tools_side_effect():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise MCPUnauthorizedException("ts1")
        return []  # success on retry

    conn = MagicMock()
    conn.get_tools_list = AsyncMock(side_effect=get_tools_side_effect)
    conn_builder = MagicMock()
    conn_builder.build.return_value = conn

    login_service = AsyncMock()
    login_service.request_signin_batch = AsyncMock(
        return_value={"toolsets/public/ts1": LoginResult.SUCCESS}
    )

    initializer, mcp_context, _ = _make_initializer(
        [ts], login_service=login_service, connection_manager_builder=conn_builder
    )
    await initializer.initialize()

    login_service.request_signin_batch.assert_awaited_once()
    # No exceptions appended — retry succeeded
    mcp_context.append_exception.assert_not_called()


@pytest.mark.asyncio
async def test_retry_failure_appends_exception():
    """Login SUCCESS but retry still fails → ToolInitializationException appended."""
    ts = _make_dial_toolset(dial_id="toolsets/public/ts1", name="ts1")

    conn = MagicMock()
    conn.get_tools_list = AsyncMock(side_effect=MCPUnauthorizedException("ts1"))
    conn_builder = MagicMock()
    conn_builder.build.return_value = conn

    login_service = AsyncMock()
    login_service.request_signin_batch = AsyncMock(
        return_value={"toolsets/public/ts1": LoginResult.SUCCESS}
    )

    initializer, mcp_context, _ = _make_initializer(
        [ts], login_service=login_service, connection_manager_builder=conn_builder
    )
    await initializer.initialize()

    # Retry also throws 401, which _retry_process_toolset catches
    assert mcp_context.append_exception.call_count == 1
    exc = mcp_context.append_exception.call_args[0][0]
    assert isinstance(exc, ToolInitializationException)
    assert "still failed" in exc.message.lower()


@pytest.mark.asyncio
async def test_plain_mcp_toolset_401_not_eligible():
    """A plain MCPToolSet returning 401 is NOT eligible for interactive login."""
    ts = _make_mcp_toolset()

    conn = MagicMock()
    conn.get_tools_list = AsyncMock(side_effect=MCPUnauthorizedException("ext"))
    conn_builder = MagicMock()
    conn_builder.build.return_value = conn

    initializer, mcp_context, login_service = _make_initializer(
        [ts], connection_manager_builder=conn_builder
    )
    await initializer.initialize()

    # MCPUnauthorizedException from plain MCPToolSet → logged, not sent to interactive login
    login_service.request_signin_batch.assert_not_awaited()


@pytest.mark.asyncio
async def test_batch_multiple_toolsets():
    """Multiple DialMCPToolSets fail with 401 → single batch login call."""
    ts1 = _make_dial_toolset(dial_id="toolsets/public/ts1", name="ts1")
    ts2 = _make_dial_toolset(dial_id="toolsets/public/ts2", name="ts2")

    conn = MagicMock()
    conn.get_tools_list = AsyncMock(side_effect=MCPUnauthorizedException("ts"))
    conn_builder = MagicMock()
    conn_builder.build.return_value = conn

    login_service = AsyncMock()
    login_service.request_signin_batch = AsyncMock(
        return_value={
            "toolsets/public/ts1": LoginResult.SUCCESS,
            "toolsets/public/ts2": LoginResult.TIMEOUT,
        }
    )

    initializer, mcp_context, _ = _make_initializer(
        [ts1, ts2], login_service=login_service, connection_manager_builder=conn_builder
    )
    await initializer.initialize()

    # Single batch call with both dial_ids
    login_service.request_signin_batch.assert_awaited_once()
    call_args = login_service.request_signin_batch.await_args[0][0]
    assert set(call_args) == {"toolsets/public/ts1", "toolsets/public/ts2"}

    # ts2 timed out → exception appended
    exceptions = [c[0][0] for c in mcp_context.append_exception.call_args_list]
    timeout_excs = [e for e in exceptions if "timed out" in e.message.lower()]
    assert len(timeout_excs) == 1


@pytest.mark.asyncio
async def test_no_channel_appends_exception():
    """Login returns NO_CHANNEL → ToolInitializationException with appropriate message."""
    ts = _make_dial_toolset(dial_id="toolsets/public/ts1", name="ts1")

    conn = MagicMock()
    conn.get_tools_list = AsyncMock(side_effect=MCPUnauthorizedException("ts1"))
    conn_builder = MagicMock()
    conn_builder.build.return_value = conn

    login_service = AsyncMock()
    login_service.request_signin_batch = AsyncMock(
        return_value={"toolsets/public/ts1": LoginResult.NO_CHANNEL}
    )

    initializer, mcp_context, _ = _make_initializer(
        [ts], login_service=login_service, connection_manager_builder=conn_builder
    )
    await initializer.initialize()

    assert mcp_context.append_exception.call_count == 1
    exc = mcp_context.append_exception.call_args[0][0]
    assert isinstance(exc, ToolInitializationException)
    assert "no client channel" in exc.message.lower()
