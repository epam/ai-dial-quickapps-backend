import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from pydantic import SecretStr

from quickapp.common.dial_settings import DialSettings
from quickapp.dial_core_services._interactive_login_service import InteractiveLoginService
from quickapp.dial_core_services._interactive_login_settings import InteractiveLoginSettings
from quickapp.dial_core_services._login_result import LoginResult


def _make_service(
    client_channel_id: str | None = "test-channel",
    timeout: float = 120.0,
) -> InteractiveLoginService:
    return InteractiveLoginService(
        api_key=SecretStr("test-key"),
        dial_settings=DialSettings(url="http://dial-core", api_version="2025-01-01-preview"),
        client_channel_id=client_channel_id,
        settings=InteractiveLoginSettings(interactive_login_timeout_seconds=timeout),
    )


class _FakeSSEEvent:
    def __init__(self, data: str | None = None):
        self.data = data


class _FakeEventSource:
    """Simulates an httpx-sse event source context manager."""

    def __init__(self, events: list[_FakeSSEEvent], status_code: int = 200):
        self.events = events
        self.response = MagicMock()
        self.response.status_code = status_code
        if status_code >= 400:
            self.response.raise_for_status.side_effect = httpx.HTTPStatusError(
                "error", request=MagicMock(), response=self.response
            )
        else:
            self.response.raise_for_status = MagicMock()

    async def aiter_sse(self):
        for event in self.events:
            yield event

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


def _patch_sse(event_source: _FakeEventSource):
    """Patch aconnect_sse to return a fake event source."""
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    return patch(
        "quickapp.dial_core_services._interactive_login_service.aconnect_sse",
        return_value=event_source,
    ), patch(
        "quickapp.dial_core_services._interactive_login_service.httpx.AsyncClient",
        return_value=mock_client,
    )


@pytest.mark.asyncio
async def test_no_channel_returns_no_channel():
    service = _make_service(client_channel_id=None)
    result = await service.request_signin_batch(["toolset/a", "toolset/b"])
    assert result == {"toolset/a": LoginResult.NO_CHANNEL, "toolset/b": LoginResult.NO_CHANNEL}


@pytest.mark.asyncio
async def test_single_success():
    data = json.dumps([{"jsonrpc": "2.0", "result": "success", "id": "1"}])
    event_source = _FakeEventSource([_FakeSSEEvent(data)])
    service = _make_service()

    sse_patch, client_patch = _patch_sse(event_source)
    with sse_patch, client_patch:
        result = await service.request_signin_batch(["toolset/a"])

    assert result == {"toolset/a": LoginResult.SUCCESS}


@pytest.mark.asyncio
async def test_batch_mixed_results():
    data = json.dumps(
        [
            {"jsonrpc": "2.0", "result": "success", "id": "1"},
            {"jsonrpc": "2.0", "result": "denied", "id": "2"},
        ]
    )
    event_source = _FakeEventSource([_FakeSSEEvent(data)])
    service = _make_service()

    sse_patch, client_patch = _patch_sse(event_source)
    with sse_patch, client_patch:
        result = await service.request_signin_batch(["toolset/a", "toolset/b"])

    assert result == {"toolset/a": LoginResult.SUCCESS, "toolset/b": LoginResult.DENIED}


@pytest.mark.asyncio
async def test_jsonrpc_error_object():
    data = json.dumps(
        [
            {"jsonrpc": "2.0", "error": {"code": -32600, "message": "Invalid"}, "id": "1"},
        ]
    )
    event_source = _FakeEventSource([_FakeSSEEvent(data)])
    service = _make_service()

    sse_patch, client_patch = _patch_sse(event_source)
    with sse_patch, client_patch:
        result = await service.request_signin_batch(["toolset/a"])

    assert result == {"toolset/a": LoginResult.ERROR}


@pytest.mark.asyncio
async def test_missing_entry_returns_error():
    """If DIAL Core response is missing an entry for a requested toolset, it maps to ERROR."""
    data = json.dumps([{"jsonrpc": "2.0", "result": "success", "id": "1"}])
    event_source = _FakeEventSource([_FakeSSEEvent(data)])
    service = _make_service()

    sse_patch, client_patch = _patch_sse(event_source)
    with sse_patch, client_patch:
        result = await service.request_signin_batch(["toolset/a", "toolset/b"])

    assert result["toolset/a"] == LoginResult.SUCCESS
    assert result["toolset/b"] == LoginResult.ERROR


@pytest.mark.asyncio
async def test_malformed_json_returns_error():
    event_source = _FakeEventSource([_FakeSSEEvent("not json")])
    service = _make_service()

    sse_patch, client_patch = _patch_sse(event_source)
    with sse_patch, client_patch:
        result = await service.request_signin_batch(["toolset/a"])

    assert result == {"toolset/a": LoginResult.ERROR}


@pytest.mark.asyncio
async def test_http_error_returns_error():
    event_source = _FakeEventSource([], status_code=404)
    service = _make_service()

    sse_patch, client_patch = _patch_sse(event_source)
    with sse_patch, client_patch:
        result = await service.request_signin_batch(["toolset/a"])

    assert result == {"toolset/a": LoginResult.ERROR}


@pytest.mark.asyncio
async def test_timeout_returns_timeout():
    service = _make_service(timeout=0.01)

    async def slow_interact(*args, **kwargs):
        import asyncio

        await asyncio.sleep(10)

    with patch.object(service, "_do_interact", side_effect=slow_interact):
        result = await service.request_signin_batch(["toolset/a"])

    assert result == {"toolset/a": LoginResult.TIMEOUT}


@pytest.mark.asyncio
async def test_empty_stream_returns_error():
    """Stream ends without any data events."""
    event_source = _FakeEventSource([])
    service = _make_service()

    sse_patch, client_patch = _patch_sse(event_source)
    with sse_patch, client_patch:
        result = await service.request_signin_batch(["toolset/a"])

    assert result == {"toolset/a": LoginResult.ERROR}


@pytest.mark.asyncio
async def test_request_signin_convenience():
    """request_signin() delegates to request_signin_batch() and returns scalar."""
    service = _make_service()
    mock_result = {"toolset/a": LoginResult.SUCCESS}
    with patch.object(service, "request_signin_batch", return_value=mock_result) as mock_batch:
        result = await service.request_signin("toolset/a")

    assert result == LoginResult.SUCCESS
    mock_batch.assert_awaited_once_with(["toolset/a"])


@pytest.mark.asyncio
async def test_single_result_not_list():
    """DIAL Core returns a single RPC response object (not a list)."""
    data = json.dumps({"jsonrpc": "2.0", "result": "success", "id": "1"})
    event_source = _FakeEventSource([_FakeSSEEvent(data)])
    service = _make_service()

    sse_patch, client_patch = _patch_sse(event_source)
    with sse_patch, client_patch:
        result = await service.request_signin_batch(["toolset/a"])

    assert result == {"toolset/a": LoginResult.SUCCESS}
