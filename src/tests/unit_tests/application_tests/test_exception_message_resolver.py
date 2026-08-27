import httpx
import openai
import pytest
from aidial_sdk.exceptions import ContextLengthExceededError as AiDialContextLengthError
from aidial_sdk.exceptions import InvalidRequestError as AiDialInvalidRequestError

from quickapp.common.exceptions import (
    FallbackAgentStopException,
    OrchestratorExceedMaxIterationsException,
    ToolErrorException,
)
from quickapp.core.application._exception_message_resolver import (
    _MSG_FALLBACK_STOP,
    _RETRY_SENTENCE,
    resolve_exception,
)
from quickapp.dial_core_services.exceptions import (
    ToolsetForbiddenException,
    ToolsetNotFoundException,
)
from quickapp.mcp_tooling._mcp_tool_error_exception import MCPToolErrorException


def _make_httpx_request() -> httpx.Request:
    return httpx.Request("GET", "http://internal-dial-core.svc.cluster.local/api")


def _make_httpx_response(status_code: int) -> httpx.Response:
    return httpx.Response(status_code, request=_make_httpx_request())


def _make_openai_status_error(
    cls: type[openai.APIStatusError], status_code: int, body: object = None
) -> openai.APIStatusError:
    return cls("raw error detail", response=_make_httpx_response(status_code), body=body)


def _make_openai_api_error(body: object) -> openai.APIError:
    return openai.APIError("raw error detail", request=_make_httpx_request(), body=body)


def _resolve(e: Exception) -> str:
    return resolve_exception(e).message


def _make_tool_error_with_cause(cause: Exception) -> ToolErrorException:
    error = ToolErrorException("rest_tool", "public tool error")
    error.__cause__ = cause
    return error


class TestResolveOpenAIError:
    def test_permission_denied(self) -> None:
        e = _make_openai_status_error(openai.PermissionDeniedError, 403)
        assert "permission" in _resolve(e).lower()

    def test_authentication_error(self) -> None:
        e = _make_openai_status_error(openai.AuthenticationError, 401)
        assert "authentication" in _resolve(e).lower()

    def test_not_found_error(self) -> None:
        e = _make_openai_status_error(openai.NotFoundError, 404)
        assert "could not be found" in _resolve(e).lower()

    def test_rate_limit_error(self) -> None:
        e = _make_openai_status_error(openai.RateLimitError, 429)
        assert "rate-limited" in _resolve(e).lower()

    def test_bad_request_error(self) -> None:
        e = _make_openai_status_error(openai.BadRequestError, 400)
        assert "rejected" in _resolve(e).lower()

    def test_internal_server_error(self) -> None:
        e = _make_openai_status_error(openai.InternalServerError, 500)
        assert "internal error" in _resolve(e).lower()

    def test_api_timeout_error(self) -> None:
        e = openai.APITimeoutError(request=_make_httpx_request())
        assert "timed out" in _resolve(e).lower()

    def test_api_connection_error(self) -> None:
        e = openai.APIConnectionError(request=_make_httpx_request())
        assert "connect" in _resolve(e).lower()

    # APITimeoutError is a subclass of APIConnectionError — ensure it does NOT fall
    # through to the connection error branch.
    def test_api_timeout_not_handled_as_connection_error(self) -> None:
        e = openai.APITimeoutError(request=_make_httpx_request())
        assert "timed out" in _resolve(e).lower()
        assert "connect" not in _resolve(e).lower()

    def test_conflict_is_retryable(self) -> None:
        e = _make_openai_status_error(openai.ConflictError, 409)
        resolved = resolve_exception(e)
        assert resolved.retryable is True
        assert resolved.message.endswith(_RETRY_SENTENCE)

    def test_payload_too_large(self) -> None:
        e = _make_openai_status_error(openai.APIStatusError, 413)
        resolved = resolve_exception(e)
        assert "payload is too large" in resolved.message.lower()
        assert resolved.retryable is False


class TestResolveHttpxError:
    def test_http_status_401(self) -> None:
        e = httpx.HTTPStatusError(
            "unauthorized", request=_make_httpx_request(), response=_make_httpx_response(401)
        )
        message = _resolve(e).lower()
        assert "authentication failed" in message
        assert "required service" in message

    def test_http_status_403(self) -> None:
        e = httpx.HTTPStatusError(
            "forbidden", request=_make_httpx_request(), response=_make_httpx_response(403)
        )
        assert "permission" in _resolve(e).lower()

    def test_http_status_404(self) -> None:
        e = httpx.HTTPStatusError(
            "not found", request=_make_httpx_request(), response=_make_httpx_response(404)
        )
        assert "could not be found" in _resolve(e).lower()

    def test_http_status_429(self) -> None:
        e = httpx.HTTPStatusError(
            "rate limit", request=_make_httpx_request(), response=_make_httpx_response(429)
        )
        assert "rate-limiting" in _resolve(e).lower()

    def test_http_status_500(self) -> None:
        e = httpx.HTTPStatusError(
            "server error", request=_make_httpx_request(), response=_make_httpx_response(500)
        )
        assert "internal error" in _resolve(e).lower()

    def test_http_status_503(self) -> None:
        e = httpx.HTTPStatusError(
            "unavailable", request=_make_httpx_request(), response=_make_httpx_response(503)
        )
        assert "internal error" in _resolve(e).lower()

    def test_http_status_422_other(self) -> None:
        e = httpx.HTTPStatusError(
            "unprocessable", request=_make_httpx_request(), response=_make_httpx_response(422)
        )
        assert "unexpected http" in _resolve(e).lower()

    def test_timeout_exception(self) -> None:
        e = httpx.TimeoutException("timed out", request=_make_httpx_request())
        assert "timed out" in _resolve(e).lower()

    def test_network_error(self) -> None:
        e = httpx.NetworkError("connection reset")
        assert "network error" in _resolve(e).lower()

    def test_generic_http_error_fallback(self) -> None:
        e = httpx.HTTPError("some low-level http error")
        assert "http error" in _resolve(e).lower()

    def test_tool_error_with_http_status_cause_uses_http_specific_message(self) -> None:
        cause = httpx.HTTPStatusError(
            "forbidden", request=_make_httpx_request(), response=_make_httpx_response(403)
        )
        e = ToolErrorException("rest_tool", "public tool error")
        e.__cause__ = cause
        assert "permission" in _resolve(e).lower()

    def test_tool_error_with_timeout_cause_uses_timeout_message(self) -> None:
        cause = httpx.TimeoutException("timed out", request=_make_httpx_request())
        e = ToolErrorException("rest_tool", "public tool error")
        e.__cause__ = cause
        assert "timed out" in _resolve(e).lower()


class TestResolveInternalError:
    def test_orchestrator_exceed_max_iterations(self) -> None:
        e = OrchestratorExceedMaxIterationsException()
        assert "max iterations" in _resolve(e).lower()

    def test_toolset_not_found_includes_id(self) -> None:
        message = _resolve(ToolsetNotFoundException("my-toolset"))
        assert "toolset" in message.lower()
        assert "my-toolset" in message

    def test_toolset_forbidden_includes_id(self) -> None:
        message = _resolve(ToolsetForbiddenException("my-toolset"))
        assert "forbidden" in message.lower()
        assert "my-toolset" in message

    def test_unknown_exception_fallback(self) -> None:
        assert "something went wrong" in _resolve(RuntimeError("boom")).lower()

    def test_generic_value_error_fallback(self) -> None:
        assert "something went wrong" in _resolve(ValueError("unexpected value")).lower()


class TestDisplayMessagePreference:
    def test_openai_display_message_used_over_canned(self) -> None:
        e = _make_openai_status_error(
            openai.InternalServerError,
            500,
            body={"error": {"display_message": "Daily token budget exhausted for this key."}},
        )
        resolved = resolve_exception(e)
        assert resolved.message == "Daily token budget exhausted for this key."

    def test_display_message_never_retry_suffixed_even_when_retryable(self) -> None:
        e = _make_openai_status_error(
            openai.InternalServerError,
            500,
            body={"error": {"display_message": "Upstream is down."}},
        )
        resolved = resolve_exception(e)
        # Classified retryable (5xx) for logging, but the upstream text is used verbatim.
        assert resolved.retryable is True
        assert resolved.message == "Upstream is down."
        assert not resolved.message.endswith(_RETRY_SENTENCE)

    def test_whitespace_only_display_message_falls_through(self) -> None:
        e = _make_openai_status_error(
            openai.InternalServerError, 500, body={"error": {"display_message": "   "}}
        )
        resolved = resolve_exception(e)
        # Sanitizes to nothing -> the status ladder resolves instead of an empty message.
        assert "internal error" in resolved.message.lower()
        assert resolved.retryable is True

    def test_display_message_truncated(self) -> None:
        long_text = "x" * 900
        e = _make_openai_status_error(
            openai.BadRequestError, 400, body={"error": {"display_message": long_text}}
        )
        resolved = resolve_exception(e)
        assert len(resolved.message) <= 500
        assert resolved.message.endswith("…")

    def test_aidial_display_message_used(self) -> None:
        e = AiDialInvalidRequestError("internal detail", display_message="Please fix your input.")
        assert resolve_exception(e).message == "Please fix your input."


class TestCodeMap:
    def test_content_filter(self) -> None:
        e = _make_openai_status_error(
            openai.BadRequestError, 400, body={"error": {"code": "content_filter"}}
        )
        resolved = resolve_exception(e)
        assert "content management policy" in resolved.message.lower()
        assert resolved.retryable is False

    def test_context_length_exceeded_on_openai_bad_request(self) -> None:
        e = _make_openai_status_error(
            openai.BadRequestError, 400, body={"error": {"code": "context_length_exceeded"}}
        )
        resolved = resolve_exception(e)
        assert "context length" in resolved.message.lower()
        assert resolved.retryable is False

    def test_context_length_on_aidial_exception(self) -> None:
        e = AiDialContextLengthError(max_context_length=1000, prompt_tokens=2000)
        assert "context length" in resolve_exception(e).message.lower()


class TestStreamFailure:
    def test_plain_api_error_without_body_is_stream_failure(self) -> None:
        resolved = resolve_exception(_make_openai_api_error(body=None))
        assert "failed while responding" in resolved.message.lower()
        assert resolved.retryable is True
        assert resolved.message.endswith(_RETRY_SENTENCE)

    def test_mid_stream_numeric_code_backfills_to_status_ladder(self) -> None:
        # DIAL defaults code to str(status); a mid-stream 429 carries code="429" and no
        # HTTP status, and must resolve to the specific rate-limit message, not stream-failure.
        resolved = resolve_exception(_make_openai_api_error(body={"code": "429"}))
        assert "rate-limited" in resolved.message.lower()
        assert resolved.retryable is True

    def test_mid_stream_unknown_code_is_stream_failure(self) -> None:
        resolved = resolve_exception(_make_openai_api_error(body={"code": "weird_upstream_code"}))
        assert "failed while responding" in resolved.message.lower()


class TestRetryabilityComposition:
    def test_retryable_appends_retry_sentence_once(self) -> None:
        resolved = resolve_exception(_make_openai_status_error(openai.InternalServerError, 500))
        assert resolved.retryable is True
        assert resolved.message.endswith(_RETRY_SENTENCE)
        assert resolved.message.count(_RETRY_SENTENCE) == 1

    def test_non_retryable_has_no_retry_sentence(self) -> None:
        resolved = resolve_exception(_make_openai_status_error(openai.PermissionDeniedError, 403))
        assert resolved.retryable is False
        assert not resolved.message.endswith(_RETRY_SENTENCE)

    def test_connection_error_is_non_retryable(self) -> None:
        resolved = resolve_exception(openai.APIConnectionError(request=_make_httpx_request()))
        assert resolved.retryable is False

    def test_network_error_is_retryable(self) -> None:
        resolved = resolve_exception(httpx.NetworkError("reset"))
        assert resolved.retryable is True
        assert resolved.message.endswith(_RETRY_SENTENCE)


class TestExtraction:
    def test_details_carried_on_resolved_error(self) -> None:
        e = _make_openai_status_error(
            openai.BadRequestError,
            400,
            body={"error": {"code": "content_filter", "type": "invalid_request_error"}},
        )
        resolved = resolve_exception(e)
        assert resolved.details.status_code == 400
        assert resolved.details.code == "content_filter"
        assert resolved.details.error_type == "invalid_request_error"

    def test_tool_error_without_cause_uses_tool_error_message(self) -> None:
        e = ToolErrorException("some_tool", "public tool error")
        resolved = _resolve(e)
        assert "some_tool" in resolved.lower()
        # The user message is built from error_message, not the structural str(e).
        assert "public tool error" in resolved
        assert "content_length" not in resolved

    def test_mcp_tool_error_without_cause_surfaces_body_not_structural_str(self) -> None:
        # str(e) is structural for logs; the user-facing message keeps the real MCP text
        # and the "MCP tool" label (tool_kind), not the generic "Tool".
        e = MCPToolErrorException("mcp_tool", "the real mcp error text")
        resolved = _resolve(e)
        assert "the real mcp error text" in resolved
        assert "MCP tool" in resolved
        assert "content_length" not in resolved

    def test_tool_error_with_non_http_cause_uses_generic_fallback(self) -> None:
        e = ToolErrorException("rest_tool", "public tool error")
        e.__cause__ = ValueError("bad value")
        assert "something went wrong" in _resolve(e).lower()


class TestNoLeakage:
    """HTTP-related exceptions must never expose internal URLs or raw error text."""

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
                _make_openai_api_error(body=None),
                id="openai-stream-failure",
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
            pytest.param(
                _make_tool_error_with_cause(
                    httpx.HTTPStatusError(
                        f"forbidden {_INTERNAL_URL}",
                        request=_make_httpx_request(),
                        response=_make_httpx_response(403),
                    )
                ),
                id="tool-error-httpx-403",
            ),
        ],
    )
    def test_no_internal_detail_leaked(self, exc: Exception) -> None:
        result = _resolve(exc)
        assert self._INTERNAL_URL not in result
        assert self._RAW_DETAIL not in result


class TestResolveFallbackStop:
    def test_stop_exception_resolves_to_stop_message(self) -> None:
        resolved = resolve_exception(FallbackAgentStopException(tool_call_id="call_1"))
        assert resolved.message == _MSG_FALLBACK_STOP
        assert resolved.retryable is False

    def test_stop_exception_message_does_not_contain_raw_error_detail(self) -> None:
        resolved = resolve_exception(FallbackAgentStopException(tool_call_id="call_1"))
        assert "FallbackAgentStopException" not in resolved.message
        assert "Traceback" not in resolved.message
