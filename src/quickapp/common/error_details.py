"""Normalized upstream error details, shared by the top-level resolver and tool stages."""

import logging
from typing import Any

import httpx
import openai
from aidial_sdk.exceptions import HTTPException as AiDialHTTPException
from pydantic import BaseModel, ConfigDict

logger = logging.getLogger(__name__)

# Appended only to retryable-classified messages (by the resolver and the deployment tool
# stage). No message constant carries it, so it is never stacked on top of conflicting advice.
RETRY_SENTENCE = "Please try again later."

# display_message is user-safe by DIAL contract but still untrusted text: capped so a
# misbehaving upstream cannot flood the chat.
_DISPLAY_MESSAGE_MAX_LEN = 500

# Retryable-classified: carries the cause only; the retry sentence is appended.
MSG_AI_MODEL_RATE_LIMITED = "The request was rate-limited by the AI model service."


class ErrorDetails(BaseModel):
    """Normalized view of an upstream error, extracted from any supported exception shape."""

    model_config = ConfigDict(frozen=True)

    status_code: int | None = None
    code: str | None = None
    error_type: str | None = None  # never influences resolution; forwarded to logs and wire `type`
    message: str | None = None  # internal message — logged, never shown to the user
    display_message: str | None = None  # user-safe by DIAL contract


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


def extract_error_details(e: Exception) -> ErrorDetails:
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


def sanitize_display_message(text: str) -> str:
    text = text.strip()
    if len(text) > _DISPLAY_MESSAGE_MAX_LEN:
        text = text[: _DISPLAY_MESSAGE_MAX_LEN - 1].rstrip() + "…"
    return text
