import base64
from unittest.mock import AsyncMock, MagicMock, Mock

import httpx
import pytest
from mcp.shared.exceptions import McpError
from mcp.types import ErrorData
from pydantic import SecretStr

from quickapp.common.dial_settings import DialSettings
from quickapp.common.oauth_token_fetcher import OAuthTokenFetcher
from quickapp.config.toolsets.authorization import (
    BasicAuthorization,
    BearerAuthorization,
    ClientIdSecretAuthorization,
    MCPApiKeyAuthorization,
)
from quickapp.config.toolsets.mcp import MCPProtocol, MCPServerInfo, MCPToolSet
from quickapp.mcp_tooling._mcp_connection_manager import _MCPConnectionManager
from quickapp.mcp_tooling._mcp_tool import _MCPTool

# noinspection PyProtectedMember
from quickapp.mcp_tooling._mcp_tool_initializer import (
    _flatten_exceptions,
    _format_leaf_for_user,
    _MCPToolInitializer,
)
from tests.unit_tests.common.common import make_provider, noop_timeout_resolver


def build_side_effect(tool, tool_config):
    return _MCPTool(
        tool=tool,
        tool_config=tool_config,
        connection_manager=MagicMock(),
        stage_wrapper_builder=MagicMock(),
        state_holder=MagicMock(),
        dial_attachment_service=MagicMock(),
        perf_timer=MagicMock(),
        file_service=MagicMock(),
        dial_toolset_id=None,
        login_service=MagicMock(),
        timeout_resolver=noop_timeout_resolver(),
        dial_settings=MagicMock(url="https://dial.example.com"),
    )


@pytest.fixture
def mock_state_holder():
    return MagicMock()


@pytest.fixture
def mock_stage_wrapper_builder():
    return MagicMock()


@pytest.fixture
def mock_connection_manager():
    return MagicMock()


@pytest.fixture
def mock_dial_attachment_service():
    return MagicMock()


@pytest.fixture
def mock_tool_config():
    return MagicMock()


@pytest.fixture
def tool1():
    tool = MagicMock(name="tool1")
    tool.name = "tool1"
    tool.description = "desc1"
    tool.inputSchema = {"type": "object", "properties": {}}
    return tool


@pytest.fixture
def tool2():
    tool = MagicMock(name="tool2")
    tool.name = "tool2"
    tool.description = "desc2"
    tool.inputSchema = {"type": "object", "properties": {}}
    return tool


@pytest.fixture
def mcp_tool1(
    tool1,
    mock_tool_config,
    mock_stage_wrapper_builder,
    mock_dial_attachment_service,
    mock_connection_manager,
    mock_state_holder,
):
    from quickapp.mcp_tooling._mcp_tool_initializer import _MCPTool

    return _MCPTool(
        tool=tool1,
        tool_config=mock_tool_config,
        connection_manager=mock_connection_manager,
        stage_wrapper_builder=mock_stage_wrapper_builder,
        dial_attachment_service=mock_dial_attachment_service,
        state_holder=mock_state_holder(),
        perf_timer=Mock(),
        file_service=MagicMock(),
        dial_toolset_id=None,
        login_service=MagicMock(),
        timeout_resolver=noop_timeout_resolver(),
        dial_settings=MagicMock(url="https://dial.example.com"),
    )


@pytest.fixture
def mcp_tool2(
    tool2,
    mock_tool_config,
    mock_stage_wrapper_builder,
    mock_dial_attachment_service,
    mock_connection_manager,
    mock_state_holder,
):
    from quickapp.mcp_tooling._mcp_tool_initializer import _MCPTool

    return _MCPTool(
        tool=tool2,
        tool_config=mock_tool_config,
        connection_manager=mock_connection_manager,
        stage_wrapper_builder=mock_stage_wrapper_builder,
        dial_attachment_service=mock_dial_attachment_service,
        state_holder=mock_state_holder(),
        perf_timer=Mock(),
        file_service=MagicMock(),
        dial_toolset_id=None,
        login_service=MagicMock(),
        timeout_resolver=noop_timeout_resolver(),
        dial_settings=MagicMock(url="https://dial.example.com"),
    )


# --- New reusable fixtures to remove duplication ---
@pytest.fixture
def connection_manager_with_tools(tool1, tool2):
    conn = MagicMock()
    conn.get_tools_list = AsyncMock(return_value=[tool1, tool2])
    return conn


@pytest.fixture
def connection_manager_builder(connection_manager_with_tools):
    b = MagicMock()
    b.build.return_value = connection_manager_with_tools
    return b


@pytest.fixture
def builder_mock():
    def side_effect(tool, tool_config, connection_manager=None, **kwargs):
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
            dial_settings=MagicMock(url="https://dial.example.com"),
        )

    m = MagicMock()
    m.build.side_effect = side_effect
    return m


@pytest.fixture
def initializer_factory(builder_mock, connection_manager_builder):
    def _create(protocol: MCPProtocol, allowed_tools=None, name="test_toolset"):
        toolset_info = MCPToolSet(
            mcp_server_info=MCPServerInfo(
                url="https://test", authorization=None, protocol=protocol
            ),
            allowed_tools=allowed_tools,
            name=name,
        )
        mcp_context = MagicMock()
        initializer = _MCPToolInitializer(
            make_provider([toolset_info]),
            mcp_context,
            MagicMock(),  # dial_setting
            MagicMock(),  # api_key_provider
            builder_mock,
            connection_manager_builder,
            MagicMock(),  # dial_mcp_cache
            MagicMock(),  # tool_config_service
            MagicMock(),  # login_service
        )
        return initializer, mcp_context

    return _create


# --- End new fixtures ---


@pytest.mark.asyncio
async def test_initialize_all_tools_appended(
    tool1, tool2, mcp_tool1, mcp_tool2, initializer_factory
):
    initializer, mcp_context = initializer_factory(protocol=MCPProtocol.sse)
    await initializer.initialize()

    assert mcp_context.extend_tools.call_count == 1
    mcp_context.extend_tools.assert_any_call([mcp_tool1, mcp_tool2])


@pytest.mark.asyncio
async def test_initialize_only_allowed_tools_appended(
    tool1, tool2, mcp_tool1, mcp_tool2, initializer_factory
):
    initializer, mcp_context = initializer_factory(
        protocol=MCPProtocol.streamable_http, allowed_tools=["tool2"]
    )
    await initializer.initialize()

    assert mcp_context.extend_tools.call_count == 1
    mcp_context.extend_tools.assert_any_call([mcp_tool2])


@pytest.mark.asyncio
async def test_initialize_no_tools_match_allowed_tools(
    tool1, tool2, mcp_tool1, mcp_tool2, initializer_factory
):
    initializer, mcp_context = initializer_factory(
        protocol=MCPProtocol.streamable_http, allowed_tools=["nonexistent"]
    )
    await initializer.initialize()
    mcp_context.append_tool.assert_not_called()
    mcp_context.extend_tools.assert_not_called()


@pytest.mark.asyncio
async def test_initialize_multiple_toolsets(tool1, tool2, builder_mock):
    mcp_context = MagicMock()

    # Two connection managers, each returning one tool
    conn1 = MagicMock()
    conn1.get_tools_list = AsyncMock(return_value=[tool1])
    conn2 = MagicMock()
    conn2.get_tools_list = AsyncMock(return_value=[tool2])

    # Builder returns conn1 for first toolset, conn2 for second
    connection_manager_builder = MagicMock()
    connection_manager_builder.build.side_effect = [conn1, conn2]

    toolset_info1 = MCPToolSet(
        mcp_server_info=MCPServerInfo(
            url="https://test1", authorization=None, protocol=MCPProtocol.streamable_http
        ),
        allowed_tools=None,
        name="test_toolset1",
    )
    toolset_info2 = MCPToolSet(
        mcp_server_info=MCPServerInfo(
            url="https://test2", authorization=None, protocol=MCPProtocol.sse
        ),
        allowed_tools=None,
        name="test_toolset2",
    )

    initializer = _MCPToolInitializer(
        make_provider([toolset_info1, toolset_info2]),
        mcp_context,
        MagicMock(),  # dial_setting
        MagicMock(),  # api_key_provider
        builder_mock,
        connection_manager_builder,
        MagicMock(),  # dial_mcp_cache
        MagicMock(),  # tool_config_service
        MagicMock(),  # login_service
    )

    await initializer.initialize()

    assert mcp_context.extend_tools.call_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "auth,header_name,expected_header",
    [
        (
            BasicAuthorization(username="user", password="test_password"),
            "Authorization",
            f"Basic {base64.b64encode(b'user:test_password').decode()}",
        ),
        (BearerAuthorization(token="token123"), "Authorization", "Bearer token123"),
        (
            MCPApiKeyAuthorization(name="api_key_name", key="api_key_value"),
            "api_key_name",
            "api_key_value",
        ),
    ],
)
async def test_connection_manager_build_headers(auth, header_name, expected_header):
    server_info = MCPServerInfo(
        url="https://test", authorization=auth, protocol=MCPProtocol.streamable_http
    )
    toolset_info = MCPToolSet(mcp_server_info=server_info, allowed_tools=None, name="set1")
    oauth_token_fetcher = AsyncMock()
    dial_settings = DialSettings(url="https://dial.test")
    conn_manager = _MCPConnectionManager(
        toolset_info=toolset_info,
        oauth_token_fetcher=oauth_token_fetcher,
        dial_settings=dial_settings,
        timeout_resolver=noop_timeout_resolver(),
    )

    headers = await conn_manager._MCPConnectionManager__build_headers(server_info)

    assert header_name in headers
    assert headers[header_name] == expected_header


@pytest.mark.asyncio
async def test_connection_manager_build_headers_client_id_secret():
    auth = ClientIdSecretAuthorization(
        client_id="client_id", client_secret="client_secret", token_url="https://token.url"
    )
    server_info = MCPServerInfo(
        url="https://test", authorization=auth, protocol=MCPProtocol.streamable_http
    )
    toolset_info = MCPToolSet(mcp_server_info=server_info, allowed_tools=None, name="set1")

    oauth_token_fetcher = MagicMock(spec=OAuthTokenFetcher)
    oauth_token_fetcher.fetch_oauth_token = AsyncMock(return_value="mock_token")
    dial_settings = DialSettings(url="https://dial.test")

    conn_manager = _MCPConnectionManager(
        toolset_info=toolset_info,
        oauth_token_fetcher=oauth_token_fetcher,
        dial_settings=dial_settings,
        timeout_resolver=noop_timeout_resolver(),
    )
    headers = await conn_manager._MCPConnectionManager__build_headers(server_info)

    assert "Authorization" in headers
    assert headers["Authorization"] == "Bearer mock_token"
    oauth_token_fetcher.fetch_oauth_token.assert_awaited_once_with(auth)


@pytest.mark.asyncio
async def test_no_exception_if_toolset_list_is_empty():
    mcp_context = MagicMock()
    initializer = _MCPToolInitializer(
        make_provider([]),  # empty toolset list
        mcp_context,
        MagicMock(),  # dial_setting
        MagicMock(),  # api_key_provider
        MagicMock(),  # tool_builder
        MagicMock(),  # connection_manager_builder
        MagicMock(),  # dial_mcp_cache
        MagicMock(),  # tool_config_service
        MagicMock(),  # login_service
    )
    await initializer.initialize()
    mcp_context.append_tool.assert_not_called()


def test_convert_to_openai_tool_dereferences_refs():
    schema = {
        "type": "object",
        "properties": {"addr": {"$ref": "#/$defs/Address"}},
        "$defs": {
            "Address": {
                "type": "object",
                "description": "Address",
                "properties": {"city": {"type": "string"}},
            }
        },
    }
    result = _MCPToolInitializer._convert_to_openai_tool("test_tool", "A test tool", schema)
    assert "addr" in result.function.parameters.properties


@pytest.mark.asyncio
async def test_tool_names_prefixed_with_toolset_name(initializer_factory, builder_mock):
    toolset_name = "mcp-local-toolset"
    initializer, _ = initializer_factory(protocol=MCPProtocol.streamable_http, name=toolset_name)
    await initializer.initialize()

    calls = builder_mock.build.call_args_list
    assert len(calls) == 2
    names = [c.kwargs["tool_config"].open_ai_tool.function.name for c in calls]
    assert names == ["mcp-local-toolset_tool1", "mcp-local-toolset_tool2"]


@pytest.mark.asyncio
async def test_connection_manager_forwards_request_bearer_for_dial_internal_server():
    server_info = MCPServerInfo(
        url="https://dial.test/mcp", authorization=None, protocol=MCPProtocol.streamable_http
    )
    toolset_info = MCPToolSet(mcp_server_info=server_info, allowed_tools=None, name="set1")

    conn_manager = _MCPConnectionManager(
        toolset_info=toolset_info,
        oauth_token_fetcher=AsyncMock(),
        dial_settings=DialSettings(url="https://dial.test"),
        timeout_resolver=noop_timeout_resolver(),
        bearer=SecretStr("request-token"),
    )

    headers = await conn_manager._MCPConnectionManager__build_headers(server_info)

    assert headers["Authorization"] == "Bearer request-token"


@pytest.mark.asyncio
async def test_connection_manager_does_not_forward_request_bearer_for_external_server():
    server_info = MCPServerInfo(
        url="https://external.test/mcp", authorization=None, protocol=MCPProtocol.streamable_http
    )
    toolset_info = MCPToolSet(mcp_server_info=server_info, allowed_tools=None, name="set1")

    conn_manager = _MCPConnectionManager(
        toolset_info=toolset_info,
        oauth_token_fetcher=AsyncMock(),
        dial_settings=DialSettings(url="https://dial.test"),
        timeout_resolver=noop_timeout_resolver(),
        bearer=SecretStr("request-token"),
    )

    headers = await conn_manager._MCPConnectionManager__build_headers(server_info)

    assert "Authorization" not in headers


@pytest.mark.asyncio
async def test_connection_manager_handles_missing_request_bearer_for_dial_internal_server():
    server_info = MCPServerInfo(
        url="https://dial.test/mcp", authorization=None, protocol=MCPProtocol.streamable_http
    )
    toolset_info = MCPToolSet(mcp_server_info=server_info, allowed_tools=None, name="set1")

    conn_manager = _MCPConnectionManager(
        toolset_info=toolset_info,
        oauth_token_fetcher=AsyncMock(),
        dial_settings=DialSettings(url="https://dial.test"),
        timeout_resolver=noop_timeout_resolver(),
        bearer=None,
    )

    headers = await conn_manager._MCPConnectionManager__build_headers(server_info)

    assert "Authorization" not in headers


# --- Error-handling helpers and integration ---


def test_flatten_exceptions_returns_leaf_for_plain_exception():
    exc = ValueError("boom")
    assert _flatten_exceptions(exc) == [exc]


def test_flatten_exceptions_unwraps_nested_groups():
    inner = ValueError("inner")
    middle = ExceptionGroup("middle", [inner])
    outer = ExceptionGroup("outer", [middle])

    assert _flatten_exceptions(outer) == [inner]


def test_flatten_exceptions_collects_multiple_leaves_in_order():
    a = ValueError("a")
    b = RuntimeError("b")
    eg = ExceptionGroup("g", [a, ExceptionGroup("g2", [b])])

    assert _flatten_exceptions(eg) == [a, b]


def test_format_leaf_renders_http_status_error():
    request = httpx.Request("POST", "http://x")
    response = httpx.Response(404, request=request)
    err = httpx.HTTPStatusError("not found", request=request, response=response)

    line = _format_leaf_for_user("My Toolset", err)

    assert line == "HTTP error for My Toolset: 404 Not Found"


def test_format_leaf_renders_session_terminated_with_404_hint():
    err = McpError(ErrorData(code=32600, message="Session terminated"))

    line = _format_leaf_for_user("My Toolset", err)

    assert "My Toolset" in line
    assert "session terminated" in line.lower()
    assert "404" in line


def test_format_leaf_renders_other_mcp_errors():
    err = McpError(ErrorData(code=-32603, message="Internal error"))

    line = _format_leaf_for_user("My Toolset", err)

    assert line == "MCP error for My Toolset: Internal error"


def test_format_leaf_renders_generic_exception():
    line = _format_leaf_for_user("My Toolset", RuntimeError("kaboom"))

    assert line == "RuntimeError: kaboom"


@pytest.mark.asyncio
async def test_initialize_surfaces_session_terminated_through_nested_exception_groups():
    """The MCP streamable_http client converts upstream HTTP 404 into nested
    ExceptionGroups containing McpError('Session terminated'). Verify we surface
    a useful message instead of leaking the raw 'unhandled errors in a TaskGroup'."""
    inner = McpError(ErrorData(code=32600, message="Session terminated"))
    nested = ExceptionGroup("inner task group", [inner])
    outer = ExceptionGroup("outer task group", [nested])

    conn = MagicMock()
    conn.get_tools_list = AsyncMock(side_effect=outer)
    conn_builder = MagicMock()
    conn_builder.build.return_value = conn

    toolset_info = MCPToolSet(
        mcp_server_info=MCPServerInfo(
            url="https://test", authorization=None, protocol=MCPProtocol.streamable_http
        ),
        allowed_tools=None,
        name="My Toolset",
    )
    mcp_context = MagicMock()
    initializer = _MCPToolInitializer(
        make_provider([toolset_info]),
        mcp_context,
        MagicMock(),  # dial_setting
        MagicMock(),  # api_key_provider
        MagicMock(),  # tool_builder
        conn_builder,
        MagicMock(),  # dial_mcp_cache
        MagicMock(),  # tool_config_service
        MagicMock(),  # login_service
    )

    await initializer.initialize()

    assert mcp_context.append_exception.call_count == 1
    appended = mcp_context.append_exception.call_args[0][0]
    assert appended.toolset_name == "My Toolset"
    assert "session terminated" in appended.message.lower()
    assert "404" in appended.message
    assert "unhandled errors in a TaskGroup" not in appended.message
    assert "unhandled errors in a TaskGroup" not in appended.details
