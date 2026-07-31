"""Tests for the external-service signin challenge reaction in _MCPTool."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from quickapp.common import ToolCallResult
from quickapp.dial_core_services._login_result import LoginResult
from quickapp.mcp_tooling._mcp_tool import _MCPTool
from quickapp.mcp_tooling._mcp_tool_error_exception import MCPToolErrorException
from tests.unit_tests.common.common import noop_timeout_resolver

_CHALLENGE_SCOPE = "applications/my-app/external_services/salesforce"
_CHALLENGE_META = {
    "dial.epam.com/error": {"status_code": 401, "external_service": "salesforce"},
    "dial.epam.com/auth-challenge": [
        {"method": "external-service/signin", "scope": _CHALLENGE_SCOPE}
    ],
}


# --- extract_external_service_signin_scope unit tests ---


def test_extract_external_service_signin_scope_found():
    result = SimpleNamespace(isError=True, meta=_CHALLENGE_META)
    assert _MCPTool._MCPTool__extract_external_service_signin_scope(result) == _CHALLENGE_SCOPE


def test_extract_external_service_signin_scope_not_error_ignored():
    """A challenge present but isError=False must be ignored (defensive; shouldn't happen)."""
    result = SimpleNamespace(isError=False, meta=_CHALLENGE_META)
    assert _MCPTool._MCPTool__extract_external_service_signin_scope(result) is None


def test_extract_external_service_signin_scope_no_meta():
    result = SimpleNamespace(isError=True, meta=None)
    assert _MCPTool._MCPTool__extract_external_service_signin_scope(result) is None


def test_extract_external_service_signin_scope_no_auth_challenge_key():
    result = SimpleNamespace(
        isError=True,
        meta={"dial.epam.com/error": {"status_code": 404, "external_service": "salesforce"}},
    )
    assert _MCPTool._MCPTool__extract_external_service_signin_scope(result) is None


def test_extract_external_service_signin_scope_wrong_method():
    result = SimpleNamespace(
        isError=True,
        meta={"dial.epam.com/auth-challenge": [{"method": "toolset/signin", "scope": "x"}]},
    )
    assert _MCPTool._MCPTool__extract_external_service_signin_scope(result) is None


def test_extract_external_service_signin_scope_not_a_list():
    result = SimpleNamespace(isError=True, meta={"dial.epam.com/auth-challenge": "not-a-list"})
    assert _MCPTool._MCPTool__extract_external_service_signin_scope(result) is None


# --- _MCPTool retry integration tests ---


def _make_mcp_tool(
    *,
    login_result: LoginResult = LoginResult.SUCCESS,
) -> tuple[_MCPTool, AsyncMock, AsyncMock]:
    """Create an _MCPTool with mocked dependencies. Returns (tool, toolset_client, login_service)."""
    tool_meta = SimpleNamespace(
        name="test_tool",
        description="test",
        inputSchema={"type": "object", "properties": {}},
    )
    tool_config = MagicMock()
    tool_config.attachment.supported_types = []

    toolset_client = AsyncMock()
    login_service = AsyncMock()
    login_service.request_external_service_signin = AsyncMock(return_value=login_result)

    mcp_tool = _MCPTool(
        tool=tool_meta,
        tool_config=tool_config,
        toolset_client=toolset_client,
        stage_wrapper_builder=MagicMock(),
        state_holder=MagicMock(),
        dial_attachment_service=MagicMock(),
        perf_timer=MagicMock(),
        file_service=MagicMock(),
        dial_toolset_id=None,
        login_service=login_service,
        timeout_resolver=noop_timeout_resolver(),
        dial_settings=MagicMock(url="https://dial.example.com"),
    )
    return mcp_tool, toolset_client, login_service


def _error_result_with_challenge():
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text="no stored credential")],
        isError=True,
        meta=_CHALLENGE_META,
    )


def _ok_result():
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text="ok")], isError=False, meta=None
    )


@pytest.mark.asyncio
async def test_challenge_triggers_signin_and_retry():
    """isError result with an auth-challenge _meta entry → signin → retry succeeds."""
    tool, conn, login = _make_mcp_tool(login_result=LoginResult.SUCCESS)
    conn.call_mcp_tool.side_effect = [_error_result_with_challenge(), _ok_result()]

    result = await tool._run_in_stage_async(None)

    assert isinstance(result, ToolCallResult)
    assert result.content == "ok"
    login.request_external_service_signin.assert_awaited_once_with(_CHALLENGE_SCOPE)
    assert conn.call_mcp_tool.await_count == 2


@pytest.mark.parametrize(
    "login_result",
    [LoginResult.DENIED, LoginResult.TIMEOUT, LoginResult.ERROR, LoginResult.NO_CHANNEL],
)
@pytest.mark.asyncio
async def test_challenge_signin_not_success_surfaces_original_error(login_result):
    """Signin not SUCCESS → original error content surfaces via MCPToolErrorException, no retry."""
    tool, conn, login = _make_mcp_tool(login_result=login_result)
    conn.call_mcp_tool.return_value = _error_result_with_challenge()

    with pytest.raises(MCPToolErrorException):
        await tool._run_in_stage_async(None)

    login.request_external_service_signin.assert_awaited_once_with(_CHALLENGE_SCOPE)
    conn.call_mcp_tool.assert_awaited_once()


@pytest.mark.asyncio
async def test_error_without_challenge_is_untouched():
    """isError result without an auth-challenge _meta entry — no signin attempt."""
    tool, conn, login = _make_mcp_tool()
    conn.call_mcp_tool.return_value = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="some other failure")],
        isError=True,
        meta={"dial.epam.com/error": {"status_code": 500, "external_service": "salesforce"}},
    )

    with pytest.raises(MCPToolErrorException):
        await tool._run_in_stage_async(None)

    login.request_external_service_signin.assert_not_awaited()
    conn.call_mcp_tool.assert_awaited_once()


@pytest.mark.asyncio
async def test_success_result_is_untouched():
    """Non-error result — no signin attempt regardless of content."""
    tool, conn, login = _make_mcp_tool()
    conn.call_mcp_tool.return_value = _ok_result()

    result = await tool._run_in_stage_async(None)

    assert result.content == "ok"
    login.request_external_service_signin.assert_not_awaited()
    conn.call_mcp_tool.assert_awaited_once()
