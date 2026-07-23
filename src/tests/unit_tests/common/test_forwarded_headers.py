"""Unit tests for forwarded_headers module (extract_x_headers_from_request)."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from starlette.datastructures import MutableHeaders

from quickapp.common.forwarded_headers import extract_x_headers_from_request


class TestExtractXHeadersFromRequest:
    """Tests for extract_x_headers_from_request."""

    def test_extract_x_headers_from_request_headers(self):
        """Headers starting with X- (case-insensitive) are extracted from request.headers."""
        request = SimpleNamespace(
            headers={
                "X-Request-Id": "req-123",
                "X-Custom-Header": "custom-value",
                "Content-Type": "application/json",
                "Authorization": "Bearer token",
            }
        )
        result = extract_x_headers_from_request(request)
        assert result == {
            "X-Request-Id": "req-123",
            "X-Custom-Header": "custom-value",
        }

    def test_extract_case_insensitive(self):
        """X- prefix matching is case-insensitive."""
        request = SimpleNamespace(
            headers={
                "x-lower": "v1",
                "X-Mixed": "v2",
                "X-UPPER": "v3",
            }
        )
        result = extract_x_headers_from_request(request)
        assert result == {"x-lower": "v1", "X-Mixed": "v2", "X-UPPER": "v3"}

    def test_extract_skips_non_x_headers(self):
        """Headers not starting with X- are not included."""
        request = SimpleNamespace(
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer x",
                "Accept": "text/plain",
            }
        )
        result = extract_x_headers_from_request(request)
        assert result is None

    def test_extract_empty_dict_returns_empty(self):
        """When request.headers is empty dict, returns empty dict."""
        request = SimpleNamespace(headers={})
        result = extract_x_headers_from_request(request)
        assert result is None

    def test_extract_from_mutable_headers(self):
        """Regression (#466): since aidial-sdk 0.38, request.headers is a Starlette
        MutableHeaders (a Mapping, not a dict); X- headers must still be extracted."""
        request = SimpleNamespace(
            headers=MutableHeaders(
                raw=[
                    (b"x-dial-client-channel-id", b"channel-abc"),
                    (b"content-type", b"application/json"),
                ]
            )
        )
        result = extract_x_headers_from_request(request)
        assert result == {"x-dial-client-channel-id": "channel-abc"}

    def test_extract_when_headers_not_mapping_returns_empty(self):
        """When request.headers is not a mapping, returns empty (no crash)."""
        request = SimpleNamespace(headers=MagicMock())
        result = extract_x_headers_from_request(request)
        assert result is None

    def test_extract_when_headers_none_returns_empty(self):
        """When request.headers is None, returns empty (no crash)."""
        request = SimpleNamespace(headers=None)
        result = extract_x_headers_from_request(request)
        assert result is None
