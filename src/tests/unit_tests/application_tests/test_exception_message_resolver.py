import httpx
import openai
import pytest

from quickapp.application._exception_message_resolver import resolve_exception_message
from quickapp.common.exceptions import OrchestratorExceedMaxIterationsException
from quickapp.dial_core_services.exceptions import (
    ToolsetForbiddenException,
    ToolsetNotFoundException,
)


def _make_httpx_request() -> httpx.Request:
    return httpx.Request("GET", "http://internal-dial-core.svc.cluster.local/api")


def _make_httpx_response(status_code: int) -> httpx.Response:
    return httpx.Response(status_code, request=_make_httpx_request())


def _make_openai_status_error(
    cls: type[openai.APIStatusError], status_code: int
) -> openai.APIStatusError:
    return cls("raw error detail", response=_make_httpx_response(status_code), body=None)


class TestResolveOpenAIError:
    def test_permission_denied(self) -> None:
        e = _make_openai_status_error(openai.PermissionDeniedError, 403)
        assert "permission" in resolve_exception_message(e).lower()

    def test_authentication_error(self) -> None:
        e = _make_openai_status_error(openai.AuthenticationError, 401)
        assert "authentication" in resolve_exception_message(e).lower()

    def test_not_found_error(self) -> None:
        e = _make_openai_status_error(openai.NotFoundError, 404)
        assert "could not be found" in resolve_exception_message(e).lower()

    def test_rate_limit_error(self) -> None:
        e = _make_openai_status_error(openai.RateLimitError, 429)
        assert "rate-limited" in resolve_exception_message(e).lower()

    def test_bad_request_error(self) -> None:
        e = _make_openai_status_error(openai.BadRequestError, 400)
        assert "rejected" in resolve_exception_message(e).lower()

    def test_internal_server_error(self) -> None:
        e = _make_openai_status_error(openai.InternalServerError, 500)
        assert "internal error" in resolve_exception_message(e).lower()

    def test_api_timeout_error(self) -> None:
        e = openai.APITimeoutError(request=_make_httpx_request())
        assert "timed out" in resolve_exception_message(e).lower()

    def test_api_connection_error(self) -> None:
        e = openai.APIConnectionError(request=_make_httpx_request())
        assert "connect" in resolve_exception_message(e).lower()

    # APITimeoutError is a subclass of APIConnectionError — ensure it does NOT fall
    # through to the connection error branch
    def test_api_timeout_not_handled_as_connection_error(self) -> None:
        e = openai.APITimeoutError(request=_make_httpx_request())
        assert "timed out" in resolve_exception_message(e).lower()
        assert "connect" not in resolve_exception_message(e).lower()


class TestResolveHttpxError:
    def test_http_status_403(self) -> None:
        e = httpx.HTTPStatusError(
            "forbidden", request=_make_httpx_request(), response=_make_httpx_response(403)
        )
        assert "permission" in resolve_exception_message(e).lower()

    def test_http_status_404(self) -> None:
        e = httpx.HTTPStatusError(
            "not found", request=_make_httpx_request(), response=_make_httpx_response(404)
        )
        assert "could not be found" in resolve_exception_message(e).lower()

    def test_http_status_429(self) -> None:
        e = httpx.HTTPStatusError(
            "rate limit", request=_make_httpx_request(), response=_make_httpx_response(429)
        )
        assert "rate-limiting" in resolve_exception_message(e).lower()

    def test_http_status_500(self) -> None:
        e = httpx.HTTPStatusError(
            "server error", request=_make_httpx_request(), response=_make_httpx_response(500)
        )
        assert "internal error" in resolve_exception_message(e).lower()

    def test_http_status_503(self) -> None:
        e = httpx.HTTPStatusError(
            "unavailable", request=_make_httpx_request(), response=_make_httpx_response(503)
        )
        assert "internal error" in resolve_exception_message(e).lower()

    def test_http_status_422_other(self) -> None:
        e = httpx.HTTPStatusError(
            "unprocessable", request=_make_httpx_request(), response=_make_httpx_response(422)
        )
        assert "unexpected http" in resolve_exception_message(e).lower()

    def test_timeout_exception(self) -> None:
        e = httpx.TimeoutException("timed out", request=_make_httpx_request())
        assert "timed out" in resolve_exception_message(e).lower()

    def test_network_error(self) -> None:
        e = httpx.NetworkError("connection reset")
        assert "network error" in resolve_exception_message(e).lower()

    def test_generic_http_error_fallback(self) -> None:
        e = httpx.HTTPError("some low-level http error")
        assert "http error" in resolve_exception_message(e).lower()


class TestResolveInternalError:
    def test_orchestrator_exceed_max_iterations(self) -> None:
        e = OrchestratorExceedMaxIterationsException()
        assert "max iterations" in resolve_exception_message(e).lower()

    def test_toolset_not_found(self) -> None:
        e = ToolsetNotFoundException("my-toolset")
        assert "toolset" in resolve_exception_message(e).lower()

    def test_toolset_forbidden(self) -> None:
        e = ToolsetForbiddenException("my-toolset")
        assert "forbidden" in resolve_exception_message(e).lower()

    def test_unknown_exception_fallback(self) -> None:
        e = RuntimeError("boom")
        assert "something went wrong" in resolve_exception_message(e).lower()

    def test_generic_value_error_fallback(self) -> None:
        e = ValueError("unexpected value")
        assert "something went wrong" in resolve_exception_message(e).lower()


class TestNoLeakage:
    """Verify that HTTP-related exceptions never expose internal URLs or raw error text."""

    _INTERNAL_URL = "http://internal-dial-core.svc.cluster.local/api"
    _RAW_DETAIL = "raw error detail"

    @pytest.mark.parametrize(
        "exc",
        [
            pytest.param(
                _make_openai_status_error(openai.PermissionDeniedError, 403),
                id="openai-403",
            ),
            pytest.param(
                _make_openai_status_error(openai.AuthenticationError, 401),
                id="openai-401",
            ),
            pytest.param(
                _make_openai_status_error(openai.InternalServerError, 500),
                id="openai-500",
            ),
            pytest.param(
                httpx.HTTPStatusError(
                    f"forbidden {_INTERNAL_URL}",
                    request=_make_httpx_request(),
                    response=_make_httpx_response(403),
                ),
                id="httpx-403",
            ),
            pytest.param(
                httpx.HTTPStatusError(
                    f"error at {_INTERNAL_URL}",
                    request=_make_httpx_request(),
                    response=_make_httpx_response(500),
                ),
                id="httpx-500",
            ),
            pytest.param(
                httpx.HTTPError(f"failure at {_INTERNAL_URL}"),
                id="httpx-generic",
            ),
        ],
    )
    def test_no_internal_detail_leaked(self, exc: Exception) -> None:
        result = resolve_exception_message(exc)
        assert self._INTERNAL_URL not in result
        assert self._RAW_DETAIL not in result
