import re

import httpx
import openai
import pytest
from aidial_sdk.exceptions import HTTPException as DialHTTPException

from quickapp.core.application._exception_message_resolver import ErrorDetails, ResolvedError
from quickapp.core.application._quick_app_completion import (
    _outgoing_status_code,
    _QuickAppCompletion,
)

# The handler is a name-mangled private static method; reach it directly for unit testing.
_handle_exception = _QuickAppCompletion._QuickAppCompletion__handle_exception  # type: ignore[attr-defined]


def _resolved(status_code: int | None) -> ResolvedError:
    return ResolvedError(
        message="msg", retryable=False, details=ErrorDetails(status_code=status_code)
    )


class TestOutgoingStatusCode:
    @pytest.mark.parametrize("status", [400, 401, 403, 404, 413, 422])
    def test_client_errors_pass_through(self, status: int) -> None:
        assert _outgoing_status_code(_resolved(status)) == status

    @pytest.mark.parametrize("status", [429, 502, 503, 504])
    def test_core_retriable_statuses_collapse_to_500(self, status: int) -> None:
        # An application cannot be retried by Core; these would have their body discarded.
        assert _outgoing_status_code(_resolved(status)) == 500

    @pytest.mark.parametrize("status", [None, 500, 409])
    def test_other_statuses_collapse_to_500(self, status: int | None) -> None:
        assert _outgoing_status_code(_resolved(status)) == 500


class TestHandleException:
    def test_raises_dial_error_with_reference(self) -> None:
        e = openai.APITimeoutError(request=httpx.Request("GET", "http://x/api"))
        with pytest.raises(DialHTTPException) as excinfo:
            _handle_exception(e)
        exc = excinfo.value
        assert exc.status_code == 500
        assert exc.type == "runtime_error"
        assert exc.display_message is not None
        assert "timed out" in exc.display_message.lower()
        assert exc.display_message == exc.message
        assert re.search(r"\(error reference: [0-9a-f]{8}\)$", exc.display_message)

    def test_client_error_status_preserved(self) -> None:
        e = openai.BadRequestError(
            "bad",
            response=httpx.Response(400, request=httpx.Request("GET", "http://x/api")),
            body=None,
        )
        with pytest.raises(DialHTTPException) as excinfo:
            _handle_exception(e)
        assert excinfo.value.status_code == 400
        # No upstream type -> the OpenAI-idiomatic default for a client-attributable 4xx.
        assert excinfo.value.type == "invalid_request_error"

    def test_rate_limit_downgraded_to_500(self) -> None:
        e = openai.RateLimitError(
            "slow",
            response=httpx.Response(429, request=httpx.Request("GET", "http://x/api")),
            body=None,
        )
        with pytest.raises(DialHTTPException) as excinfo:
            _handle_exception(e)
        assert excinfo.value.status_code == 500
        # The default type keys on the *outgoing* (downgraded) status, not the upstream one.
        assert excinfo.value.type == "runtime_error"

    def test_code_and_type_propagated_to_wire(self) -> None:
        e = openai.BadRequestError(
            "blocked",
            response=httpx.Response(400, request=httpx.Request("GET", "http://x/api")),
            body={"error": {"code": "content_filter", "type": "invalid_request_error"}},
        )
        with pytest.raises(DialHTTPException) as excinfo:
            _handle_exception(e)
        exc = excinfo.value
        assert exc.code == "content_filter"
        assert exc.type == "invalid_request_error"
