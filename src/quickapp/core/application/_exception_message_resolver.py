import logging
from typing import Any

import httpx
import openai
from aidial_sdk.exceptions import HTTPException as AiDialHTTPException
from pydantic import BaseModel, ConfigDict

from quickapp.common.exceptions import (
    FallbackAgentStopException,
    OrchestratorExceedMaxIterationsException,
    OrchestratorInitializationException,
    ToolErrorException,
)
from quickapp.dial_core_services.exceptions import (
    ToolsetForbiddenException,
    ToolsetNotFoundException,
)

logger = logging.getLogger(__name__)

# Appended by the resolver to any retryable-classified message — and only those. No
# message constant carries it, so it is never stacked on top of conflicting advice.
_RETRY_SENTENCE = "Please try again later."

# display_message is user-safe by DIAL contract but still untrusted text: capped so a
# misbehaving upstream cannot flood the chat.
_DISPLAY_MESSAGE_MAX_LEN = 500


_FALLBACK_MESSAGE = (
    "Something went wrong with the execution of your request. Please contact your administrator."
)

# --- AI-model wording (orchestrator LLM call) ---
# Retryable-classified constants carry the cause only; the retry sentence is appended.
_MSG_AI_MODEL_RATE_LIMITED = "The request was rate-limited by the AI model service."
_MSG_AI_MODEL_INTERNAL_ERROR = "The AI model service encountered an internal error."
_MSG_AI_MODEL_TIMEOUT = "The request to the AI model service timed out."
_MSG_AI_MODEL_STREAM_FAILURE = "The AI model service failed while responding."
_MSG_AI_MODEL_CONFLICT = "The AI model service reported a temporary conflict."

# Non-retryable constants carry the cause plus cause-specific advice.
_MSG_AI_MODEL_NO_PERMISSION = (
    "You don't have permission to use the AI model configured in this application. "
    "Please contact your administrator."
)
_MSG_AI_MODEL_AUTH_FAILED = (
    "Authentication failed when accessing the AI model. Please contact your administrator."
)
_MSG_AI_MODEL_NOT_FOUND = (
    "The AI model configured in this application could not be found. "
    "Please contact your administrator."
)
_MSG_AI_MODEL_INVALID_REQUEST = (
    "The request was rejected as invalid by the AI model service. "
    "Please contact your administrator."
)
_MSG_AI_MODEL_CONTENT_FILTER = (
    "The request was blocked by the content management policy. Please rephrase your message."
)
_MSG_AI_MODEL_CONTEXT_LENGTH = (
    "The request exceeds the maximum context length of the AI model. "
    "Please shorten your messages and try again."
)
_MSG_AI_MODEL_PAYLOAD_TOO_LARGE = (
    "The request payload is too large. Please reduce the size of your message or attachments."
)

# --- Service wording (DIAL core service calls surfaced as httpx errors) ---
_MSG_SERVICE_RATE_LIMITED = "A required service is currently rate-limiting requests."
_MSG_SERVICE_INTERNAL_ERROR = "A required service encountered an internal error."
_MSG_SERVICE_TIMEOUT = "A request to a required service timed out."
_MSG_SERVICE_NETWORK_ERROR = "A network error occurred while contacting a required service."

_MSG_SERVICE_NO_PERMISSION = (
    "You don't have permission to access a required service. Please contact your administrator."
)
_MSG_SERVICE_AUTH_FAILED = (
    "Authentication failed when accessing a required service. Please contact your administrator."
)
_MSG_SERVICE_NOT_FOUND = (
    "A required service or resource could not be found. Please contact your administrator."
)
_MSG_SERVICE_NO_CONNECTIVITY = (
    "Could not connect to the AI model service. "
    "Please check connectivity or contact your administrator."
)
_MSG_HTTP_UNEXPECTED = (
    "An unexpected HTTP error occurred. Please try again or contact your administrator."
)
_MSG_HTTP_GENERIC = "An HTTP error occurred. Please try again or contact your administrator."

# --- Internal / orchestration wording ---
_MSG_FALLBACK_STOP = (
    "A tool encountered an error and the agent was stopped. "
    "Please try again or contact your administrator if the issue persists."
)

# Error codes that resolve to a specific message ahead of the status ladder. All are
# non-retryable: re-sending the same request will not change the outcome.
_CODE_MESSAGES: dict[str, str] = {
    "content_filter": _MSG_AI_MODEL_CONTENT_FILTER,
    "context_length_exceeded": _MSG_AI_MODEL_CONTEXT_LENGTH,
    "truncate_prompt_error": _MSG_AI_MODEL_CONTEXT_LENGTH,
}


class ErrorDetails(BaseModel):
    """Normalized view of an upstream error, extracted from any supported exception shape."""

    model_config = ConfigDict(frozen=True)

    status_code: int | None = None
    code: str | None = None
    error_type: str | None = None  # never influences resolution; forwarded to logs and wire `type`
    message: str | None = None  # internal message — logged, never shown to the user
    display_message: str | None = None  # user-safe by DIAL contract


class ResolvedError(BaseModel):
    """Resolution result: user-facing text plus classification and the raw details."""

    model_config = ConfigDict(frozen=True)

    message: str  # user-facing text, sanitized, retry suffix already composed
    retryable: bool  # classification — logged by the handler; not re-applied to the text
    details: ErrorDetails  # extracted internals, carried for the handler's log record


# A resolved (cause message, retryable) pair, before the retry sentence is composed in.
_Resolution = tuple[str, bool]


def _unwrap_error_body(body: Any) -> dict[str, Any]:
    """Return the DIAL error object from a response/exception body.

    openai populates its ``.code`` / ``.type`` attributes from the *top level* of the
    response body, but DIAL Core nests those fields under ``error`` for 4xx/5xx
    responses (``{"error": {...}}``). Mid-stream errors are already unwrapped by the SDK,
    so ``body.get("error", body)`` is a no-op for them and the correct unwrap otherwise.
    The same nesting applies to raw httpx JSON error bodies, so both paths share this.
    """
    if not isinstance(body, dict):
        return {}
    inner = body.get("error", body)
    return inner if isinstance(inner, dict) else {}


def _backfill_status_from_code(status_code: int | None, code: str | None) -> int | None:
    """Recover a status for shapes that carry none of their own.

    DIAL defaults ``code`` to ``str(status_code)``, so a mid-stream ``APIError`` (which
    has no HTTP status) frequently carries e.g. ``code="429"``. Backfill lets those
    resolve through the ordinary status ladder.
    """
    if status_code is None and code is not None and code.isdigit():
        return int(code)
    return status_code


def _details_from_body(status_code: int | None, body: dict[str, Any]) -> ErrorDetails:
    raw_code = body.get("code")
    code = str(raw_code) if raw_code is not None else None
    return ErrorDetails(
        status_code=_backfill_status_from_code(status_code, code),
        code=code,
        error_type=body.get("type"),
        message=body.get("message"),
        display_message=body.get("display_message"),
    )


def _extract_from_openai(e: openai.APIError) -> ErrorDetails:
    # Only APIStatusError carries a status code; plain/mid-stream APIError does not.
    status_code = getattr(e, "status_code", None)
    return _details_from_body(status_code, _unwrap_error_body(e.body))


def _extract_from_aidial(e: AiDialHTTPException) -> ErrorDetails:
    return ErrorDetails(
        status_code=e.status_code,
        code=e.code,
        error_type=e.type,
        message=e.message,
        display_message=e.display_message,
    )


def _extract_from_httpx(e: httpx.HTTPError) -> ErrorDetails:
    if not isinstance(e, httpx.HTTPStatusError):
        return ErrorDetails()
    try:
        parsed = e.response.json()
    except Exception:
        parsed = None
    return _details_from_body(e.response.status_code, _unwrap_error_body(parsed))


def _extract_error_details(e: Exception) -> ErrorDetails:
    """Best-effort, total: malformed or absent bodies yield an empty ``ErrorDetails``."""
    try:
        if isinstance(e, openai.APIError):
            return _extract_from_openai(e)
        if isinstance(e, AiDialHTTPException):
            return _extract_from_aidial(e)
        if isinstance(e, httpx.HTTPError):
            return _extract_from_httpx(e)
    except Exception:
        logger.debug("Failed to extract error details from %s", type(e), exc_info=True)
    return ErrorDetails()


def _resolve_by_code(details: ErrorDetails) -> _Resolution | None:
    if details.code is None:
        return None
    message = _CODE_MESSAGES.get(details.code)
    return (message, False) if message is not None else None


def _resolve_ai_model_status(status: int | None) -> _Resolution | None:
    if status is None:
        return None
    if status == 401:
        return (_MSG_AI_MODEL_AUTH_FAILED, False)
    if status == 403:
        return (_MSG_AI_MODEL_NO_PERMISSION, False)
    if status == 404:
        return (_MSG_AI_MODEL_NOT_FOUND, False)
    if status == 413:
        return (_MSG_AI_MODEL_PAYLOAD_TOO_LARGE, False)
    if status in (400, 422):
        return (_MSG_AI_MODEL_INVALID_REQUEST, False)
    if status == 409:
        return (_MSG_AI_MODEL_CONFLICT, True)
    if status == 429:
        return (_MSG_AI_MODEL_RATE_LIMITED, True)
    if status >= 500:
        return (_MSG_AI_MODEL_INTERNAL_ERROR, True)
    return None


def _resolve_openai_status_or_type(e: openai.APIError, details: ErrorDetails) -> _Resolution | None:
    # Type branches carry no HTTP status. APITimeoutError must precede APIConnectionError
    # (it is a subclass), and both must precede the stream-failure rule.
    if isinstance(e, openai.APITimeoutError):
        return (_MSG_AI_MODEL_TIMEOUT, True)
    if isinstance(e, openai.APIConnectionError):
        # The openai client already retried this; a lingering failure is deterministic
        # (wrong endpoint / DNS / TLS), so it is non-retryable with admin-escalation advice.
        return (_MSG_SERVICE_NO_CONNECTIVITY, False)
    return _resolve_ai_model_status(details.status_code)


def _resolve_httpx_status_or_type(e: httpx.HTTPError, details: ErrorDetails) -> _Resolution:
    # httpx is a terminal source (no stream-failure fallthrough), so it always resolves.
    if isinstance(e, httpx.TimeoutException):
        return (_MSG_SERVICE_TIMEOUT, True)
    if isinstance(e, httpx.NetworkError):
        return (_MSG_SERVICE_NETWORK_ERROR, True)
    if isinstance(e, httpx.HTTPStatusError):
        status = details.status_code
        if status == 401:
            return (_MSG_SERVICE_AUTH_FAILED, False)
        if status == 403:
            return (_MSG_SERVICE_NO_PERMISSION, False)
        if status == 404:
            return (_MSG_SERVICE_NOT_FOUND, False)
        if status == 429:
            return (_MSG_SERVICE_RATE_LIMITED, True)
        if status is not None and status >= 500:
            return (_MSG_SERVICE_INTERNAL_ERROR, True)
        return (_MSG_HTTP_UNEXPECTED, False)
    return (_MSG_HTTP_GENERIC, False)


def _resolve_status_or_type(e: Exception, details: ErrorDetails) -> _Resolution | None:
    if isinstance(e, openai.APIError):
        return _resolve_openai_status_or_type(e, details)
    if isinstance(e, AiDialHTTPException):
        return _resolve_ai_model_status(details.status_code)
    if isinstance(e, httpx.HTTPError):
        return _resolve_httpx_status_or_type(e, details)
    return None


def _resolve_tool_error(e: ToolErrorException) -> ResolvedError | None:
    """Resolve a ToolErrorException.

    - If it wraps an httpx cause, delegate to the cause's resolution so the caller gets
      the appropriate HTTP-specific message (e.g. permission-denied, timeout).
    - If there is no cause, expose the tool error text directly via
      ``user_facing_message`` rather than ``str(e)``: the exception's string form is
      structural by the content rule (issue #436), while the user channel keeps the real
      text.
    - If the cause is something other than an httpx error, return None to fall through
      to the generic fallback.
    """
    if isinstance(e.__cause__, httpx.HTTPError):
        return resolve_exception(e.__cause__)
    if e.__cause__ is None:
        return _compose(e.user_facing_message, False, ErrorDetails())
    return None


def _resolve_internal(e: Exception) -> _Resolution | None:
    if isinstance(e, FallbackAgentStopException):
        return (_MSG_FALLBACK_STOP, False)
    if isinstance(e, OrchestratorExceedMaxIterationsException):
        return (str(e), False)
    if isinstance(e, OrchestratorInitializationException):
        return (_MSG_AI_MODEL_NOT_FOUND, False)
    if isinstance(e, ToolsetNotFoundException):
        toolset = f" ({e.toolset_id})" if e.toolset_id else ""
        return (
            f"A required toolset{toolset} could not be found. "
            "Please contact your administrator.",
            False,
        )
    if isinstance(e, ToolsetForbiddenException):
        toolset = f" ({e.toolset_id})" if e.toolset_id else ""
        return (
            f"Access to a required toolset{toolset} is forbidden. "
            "Please contact your administrator.",
            False,
        )
    return None


def _sanitize_display_message(text: str) -> str:
    text = text.strip()
    if len(text) > _DISPLAY_MESSAGE_MAX_LEN:
        text = text[: _DISPLAY_MESSAGE_MAX_LEN - 1].rstrip() + "…"
    return text


def _is_retryable_from_details(details: ErrorDetails) -> bool:
    """Derive retryability from status/code for the display_message path (rule 1).

    Follows the same classification as the status ladder, defaulting to ``False`` when
    neither a status nor a known code is available.
    """
    if details.code in _CODE_MESSAGES:
        return False
    status = details.status_code
    if status is None:
        return False
    if status in (409, 429):
        return True
    return status >= 500


def _compose(message: str, retryable: bool, details: ErrorDetails) -> ResolvedError:
    text = f"{message} {_RETRY_SENTENCE}" if retryable else message
    return ResolvedError(message=text, retryable=retryable, details=details)


def resolve_exception(e: Exception) -> ResolvedError:
    """Resolve any exception into user-facing text plus a retryability classification.

    Precedence: display_message -> code map -> status/type map -> stream-failure rule ->
    internal map -> tool-error -> fallback. Never leaks raw internal detail: only
    ``display_message`` (user-safe by contract) and curated canned messages reach the user.
    """
    details = _extract_error_details(e)

    # 1. Upstream-authored, user-safe text wins. Used as-is (never retry-suffixed), since
    #    appending generic advice can contradict a precise upstream explanation. A message
    #    that sanitizes to nothing (whitespace-only) falls through to the rules below.
    if details.display_message:
        display_message = _sanitize_display_message(details.display_message)
        if display_message:
            return ResolvedError(
                message=display_message,
                retryable=_is_retryable_from_details(details),
                details=details,
            )

    # 2. Specific, actionable error codes.
    resolution = _resolve_by_code(details)
    if resolution is not None:
        return _compose(*resolution, details)

    # 3. Status / type ladders (source-specific wording; unmatched -> None to continue).
    resolution = _resolve_status_or_type(e, details)
    if resolution is not None:
        return _compose(*resolution, details)

    # 4. Mid-stream openai APIError with no usable status/code — terminal for the stream
    #    path, so a mid-stream failure can never reach the generic fallback.
    if isinstance(e, openai.APIError) and not isinstance(e, openai.APIStatusError):
        return _compose(_MSG_AI_MODEL_STREAM_FAILURE, True, details)

    # 5. Internal, in-process exceptions.
    resolution = _resolve_internal(e)
    if resolution is not None:
        return _compose(*resolution, details)

    # 6. Tool errors: delegate to cause-aware resolution.
    if isinstance(e, ToolErrorException):
        resolved = _resolve_tool_error(e)
        if resolved is not None:
            return resolved

    # 7. Generic fallback (non-retryable).
    return _compose(_FALLBACK_MESSAGE, False, details)
