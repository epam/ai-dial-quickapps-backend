import httpx
import openai

from quickapp.common.exceptions import OrchestratorExceedMaxIterationsException
from quickapp.dial_core_services.exceptions import (
    ToolsetForbiddenException,
    ToolsetNotFoundException,
)

_FALLBACK_MESSAGE = (
    "Something went wrong with the execution of your request. "
    "Please try again or contact your administrator."
)


def _resolve_openai_error(e: openai.OpenAIError) -> str:
    if isinstance(e, openai.PermissionDeniedError):
        return (
            "You don't have permission to use the AI model configured in this application. "
            "Please contact your administrator."
        )
    if isinstance(e, openai.AuthenticationError):
        return (
            "Authentication failed when accessing the AI model. Please contact your administrator."
        )
    if isinstance(e, openai.NotFoundError):
        return (
            "The AI model configured in this application could not be found. "
            "Please contact your administrator."
        )
    if isinstance(e, openai.RateLimitError):
        return "The request was rate-limited by the AI model service. Please try again later."
    if isinstance(e, openai.BadRequestError):
        return (
            "The request was rejected by the AI model service. "
            "Please try again or contact your administrator."
        )
    if isinstance(e, openai.InternalServerError):
        return "The AI model service encountered an internal error. Please try again later."
    # APITimeoutError must be checked before APIConnectionError — it is a subclass of it
    if isinstance(e, openai.APITimeoutError):
        return "The request to the AI model service timed out. Please try again later."
    if isinstance(e, openai.APIConnectionError):
        return (
            "Could not connect to the AI model service. "
            "Please check connectivity or contact your administrator."
        )
    return _FALLBACK_MESSAGE


def _resolve_httpx_error(e: httpx.HTTPError) -> str:
    if isinstance(e, httpx.HTTPStatusError):
        status = e.response.status_code
        if status == 403:
            return (
                "You don't have permission to access a required service. "
                "Please contact your administrator."
            )
        if status == 404:
            return "A required service or resource could not be found. Please contact your administrator."
        if status == 429:
            return "A required service is currently rate-limiting requests. Please try again later."
        if status >= 500:
            return "A required service encountered an internal error. Please try again later."
        return "An unexpected HTTP error occurred. Please try again or contact your administrator."
    # TimeoutException must be checked before NetworkError — it is a subclass of TransportError,
    # not NetworkError, but keeping it explicit avoids future confusion
    if isinstance(e, httpx.TimeoutException):
        return "A request to a required service timed out. Please try again later."
    if isinstance(e, httpx.NetworkError):
        return (
            "A network error occurred while contacting a required service. "
            "Please try again later."
        )
    return "An HTTP error occurred. Please try again or contact your administrator."


def _resolve_internal_error(e: Exception) -> str:
    if isinstance(e, OrchestratorExceedMaxIterationsException):
        return str(e)
    if isinstance(e, ToolsetNotFoundException):
        return "A required toolset could not be found. Please contact your administrator."
    if isinstance(e, ToolsetForbiddenException):
        return "Access to a required toolset is forbidden. Please contact your administrator."
    return _FALLBACK_MESSAGE


def resolve_exception_message(e: Exception) -> str:
    """Return a safe, user-friendly message for any exception."""
    if isinstance(e, openai.OpenAIError):
        return _resolve_openai_error(e)
    if isinstance(e, httpx.HTTPError):
        return _resolve_httpx_error(e)
    return _resolve_internal_error(e)
