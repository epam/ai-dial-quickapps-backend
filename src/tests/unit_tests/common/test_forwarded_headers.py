"""Unit tests for forwarded_headers module (extract_x_headers_from_request and ForwardedHeaders)."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from quickapp.common.forwarded_headers import (
    ForwardedHeaders,
    extract_x_headers_from_request,
)


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
        assert result == {}

    def test_extract_empty_dict_returns_empty(self):
        """When request.headers is empty dict, returns empty dict."""
        request = SimpleNamespace(headers={})
        result = extract_x_headers_from_request(request)
        assert result == {}

    def test_extract_when_headers_not_dict_returns_empty(self):
        """When request.headers is not a dict, returns empty (no crash)."""
        request = SimpleNamespace(headers=MagicMock())
        result = extract_x_headers_from_request(request)
        assert result == {}

    def test_extract_when_headers_none_returns_empty(self):
        """When request.headers is None, returns empty (no crash)."""
        request = SimpleNamespace(headers=None)
        result = extract_x_headers_from_request(request)
        assert result == {}


class TestForwardedHeaders:
    """Tests for ForwardedHeaders class."""

    def test_init_none(self):
        """Initializing with None gives empty headers."""
        fh = ForwardedHeaders(None)
        assert fh.headers == {}

    def test_init_empty_dict(self):
        """Initializing with empty dict gives empty headers."""
        fh = ForwardedHeaders({})
        assert fh.headers == {}

    def test_init_with_headers(self):
        """Initializing with a dict exposes headers via .headers property."""
        h = {"X-A": "a", "X-B": "b"}
        fh = ForwardedHeaders(h)
        assert fh.headers == {"X-A": "a", "X-B": "b"}

    def test_headers_is_copy(self):
        """Internal storage is a copy; mutating the passed dict does not change ForwardedHeaders."""
        h = {"X-A": "a"}
        fh = ForwardedHeaders(h)
        h["X-B"] = "b"
        assert fh.headers == {"X-A": "a"}

    def test_headers_property_returns_dict(self):
        """.headers returns a dict suitable for merging into requests."""
        fh = ForwardedHeaders({"X-Test": "value"})
        assert isinstance(fh.headers, dict)
        assert fh.headers["X-Test"] == "value"
