"""Tests for the external-service signin challenge reaction in _MCPToolsetClient.call_mcp_tool()."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from quickapp.config.toolsets.mcp import MCPProtocol, MCPServerInfo, MCPToolSet
from quickapp.dial_core_services._login_result import LoginResult
from quickapp.mcp_tooling._mcp_toolset_client import (
    _extract_external_service_signin_url,
    _MCPToolsetClient,
)
from tests.unit_tests.common.common import noop_timeout_resolver

_CHALLENGE_URL = "applications/my-app/external_services/salesforce"
_CHALLENGE_META = {
    "dial.epam.com/error": {"status_code": 401, "external_service": "salesforce"},
    "dial.epam.com/auth-challenge": [
        {"method": "external-service/signin", "scope": _CHALLENGE_URL}
    ],
}


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


# --- _extract_external_service_signin_url unit tests ---


def test_extract_external_service_signin_url_found():
    assert _extract_external_service_signin_url(_error_result_with_challenge()) == _CHALLENGE_URL


def test_extract_external_service_signin_url_not_error_ignored():
    """A challenge present but isError=False must be ignored (defensive; shouldn't happen)."""
    result = SimpleNamespace(isError=False, meta=_CHALLENGE_META)
    assert _extract_external_service_signin_url(result) is None


def test_extract_external_service_signin_url_no_meta():
    result = SimpleNamespace(isError=True, meta=None)
    assert _extract_external_service_signin_url(result) is None


def test_extract_external_service_signin_url_no_auth_challenge_key():
    result = SimpleNamespace(
        isError=True,
        meta={"dial.epam.com/error": {"status_code": 404, "external_service": "salesforce"}},
    )
    assert _extract_external_service_signin_url(result) is None


def test_extract_external_service_signin_url_wrong_method():
    result = SimpleNamespace(
        isError=True,
        meta={"dial.epam.com/auth-challenge": [{"method": "toolset/signin", "scope": "x"}]},
    )
    assert _extract_external_service_signin_url(result) is None


def test_extract_external_service_signin_url_not_a_list():
    result = SimpleNamespace(isError=True, meta={"dial.epam.com/auth-challenge": "not-a-list"})
    assert _extract_external_service_signin_url(result) is None


# --- call_mcp_tool retry integration tests ---


def _make_toolset_client(
    *, login_result: LoginResult = LoginResult.SUCCESS
) -> tuple[_MCPToolsetClient, AsyncMock, AsyncMock]:
    """Returns (client, session, login_service). `session.call_tool` drives call_mcp_tool's result."""
    toolset = MCPToolSet(
        mcp_server_info=MCPServerInfo(
            url="https://test-mcp", authorization=None, protocol=MCPProtocol.streamable_http
        ),
        name="test-toolset",
    )
    session = AsyncMock()
    session_manager = AsyncMock()
    session_manager.get_session = AsyncMock(return_value=session)
    login_service = AsyncMock()
    login_service.request_external_service_signin = AsyncMock(return_value=login_result)

    client = _MCPToolsetClient(
        toolset_info=toolset,
        toolset_key="mcp:test-toolset",
        oauth_token_fetcher=MagicMock(),
        dial_settings=MagicMock(url="https://dial-core"),
        timeout_resolver=noop_timeout_resolver(),
        session_manager=session_manager,
        login_service=login_service,
    )
    return client, session, login_service


@pytest.mark.asyncio
async def test_challenge_triggers_signin_and_retry():
    client, session, login_service = _make_toolset_client(login_result=LoginResult.SUCCESS)
    session.call_tool.side_effect = [_error_result_with_challenge(), _ok_result()]

    result = await client.call_mcp_tool("some_tool", arg="val")

    assert result.isError is False
    login_service.request_external_service_signin.assert_awaited_once_with(_CHALLENGE_URL)
    assert session.call_tool.await_count == 2


@pytest.mark.parametrize(
    "login_result",
    [LoginResult.DENIED, LoginResult.TIMEOUT, LoginResult.ERROR, LoginResult.NO_CHANNEL],
)
@pytest.mark.asyncio
async def test_challenge_signin_not_success_returns_original_error(login_result):
    """Signin not SUCCESS → original errored result is returned unchanged, no retry call."""
    client, session, login_service = _make_toolset_client(login_result=login_result)
    error_result = _error_result_with_challenge()
    session.call_tool.return_value = error_result

    result = await client.call_mcp_tool("some_tool")

    assert result is error_result
    login_service.request_external_service_signin.assert_awaited_once_with(_CHALLENGE_URL)
    session.call_tool.assert_awaited_once()


@pytest.mark.asyncio
async def test_error_without_challenge_is_untouched():
    client, session, login_service = _make_toolset_client()
    error_result = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="some other failure")],
        isError=True,
        meta={"dial.epam.com/error": {"status_code": 500, "external_service": "salesforce"}},
    )
    session.call_tool.return_value = error_result

    result = await client.call_mcp_tool("some_tool")

    assert result is error_result
    login_service.request_external_service_signin.assert_not_awaited()
    session.call_tool.assert_awaited_once()


@pytest.mark.asyncio
async def test_success_result_is_untouched():
    client, session, login_service = _make_toolset_client()
    session.call_tool.return_value = _ok_result()

    result = await client.call_mcp_tool("some_tool")

    assert result.isError is False
    login_service.request_external_service_signin.assert_not_awaited()
    session.call_tool.assert_awaited_once()
