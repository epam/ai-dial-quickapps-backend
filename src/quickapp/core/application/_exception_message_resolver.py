import httpx
import openai
from aidial_sdk.exceptions import ContextLengthExceededError, DeploymentNotFoundError
from aidial_sdk.exceptions import HTTPException as AiDialHTTPException
from aidial_sdk.exceptions import InvalidRequestError, RequestValidationError, ResourceNotFoundError

from quickapp.common.exceptions import (
    OrchestratorExceedMaxIterationsException,
    OrchestratorInitializationException,
    ToolErrorException,
)
from quickapp.dial_core_services.exceptions import (
    ToolsetForbiddenException,
    ToolsetNotFoundException,
)

_FALLBACK_MESSAGE = (
    "Something went wrong with the execution of your request. "
    "Please try again or contact your administrator."
)


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
_MSG_AI_MODEL_RATE_LIMITED = (
    "The request was rate-limited by the AI model service. Please try again later."
)
_MSG_AI_MODEL_INVALID_REQUEST = (
    "The request was rejected as invalid by the AI model service. "
    "Please try again or contact your administrator."
)
_MSG_AI_MODEL_INTERNAL_ERROR = (
    "The AI model service encountered an internal error. Please try again later."
)
_MSG_AI_MODEL_TIMEOUT = "The request to the AI model service timed out. Please try again later."
_MSG_AI_MODEL_CONTEXT_LENGTH = (
    "The request exceeds the maximum context length of the AI model. "
    "Please shorten your messages and try again."
)

_MSG_SERVICE_NO_PERMISSION = (
    "You don't have permission to access a required service. " "Please contact your administrator."
)
_MSG_SERVICE_NOT_FOUND = (
    "A required service or resource could not be found. Please contact your administrator."
)
_MSG_SERVICE_RATE_LIMITED = (
    "A required service is currently rate-limiting requests. Please try again later."
)
_MSG_SERVICE_INTERNAL_ERROR = (
    "A required service encountered an internal error. Please try again later."
)
_MSG_SERVICE_TIMEOUT = "A request to a required service timed out. Please try again later."
_MSG_SERVICE_NETWORK_ERROR = (
    "A network error occurred while contacting a required service. " "Please try again later."
)
_MSG_SERVICE_NO_CONNECTIVITY = (
    "Could not connect to the AI model service. "
    "Please check connectivity or contact your administrator."
)


def _resolve_openai_error(e: openai.OpenAIError) -> str:
    if isinstance(e, openai.PermissionDeniedError):
        return _MSG_AI_MODEL_NO_PERMISSION
    if isinstance(e, openai.AuthenticationError):
        return _MSG_AI_MODEL_AUTH_FAILED
    if isinstance(e, openai.NotFoundError):
        return _MSG_AI_MODEL_NOT_FOUND
    if isinstance(e, openai.RateLimitError):
        return _MSG_AI_MODEL_RATE_LIMITED
    if isinstance(e, openai.BadRequestError):
        return (
            "The request was rejected by the AI model service. "
            "Please try again or contact your administrator."
        )
    if isinstance(e, openai.InternalServerError):
        return _MSG_AI_MODEL_INTERNAL_ERROR
    # APITimeoutError must be checked before APIConnectionError — it is a subclass of it
    if isinstance(e, openai.APITimeoutError):
        return _MSG_AI_MODEL_TIMEOUT
    if isinstance(e, openai.APIConnectionError):
        return _MSG_SERVICE_NO_CONNECTIVITY
    return _FALLBACK_MESSAGE


def _resolve_httpx_error(e: httpx.HTTPError) -> str:
    if isinstance(e, httpx.HTTPStatusError):
        status = e.response.status_code
        if status == 403:
            return _MSG_SERVICE_NO_PERMISSION
        if status == 404:
            return _MSG_SERVICE_NOT_FOUND
        if status == 429:
            return _MSG_SERVICE_RATE_LIMITED
        if status >= 500:
            return _MSG_SERVICE_INTERNAL_ERROR
        return "An unexpected HTTP error occurred. Please try again or contact your administrator."
    # TimeoutException must be checked before NetworkError — it is a subclass of TransportError,
    # not NetworkError, but keeping it explicit avoids future confusion
    if isinstance(e, httpx.TimeoutException):
        return _MSG_SERVICE_TIMEOUT
    if isinstance(e, httpx.NetworkError):
        return _MSG_SERVICE_NETWORK_ERROR
    return "An HTTP error occurred. Please try again or contact your administrator."


def _resolve_aidial_error(e: AiDialHTTPException) -> str:
    # ContextLengthExceededError must be checked before InvalidRequestError — it is a subclass of it
    if isinstance(e, ContextLengthExceededError):
        return _MSG_AI_MODEL_CONTEXT_LENGTH
    if isinstance(e, (InvalidRequestError, RequestValidationError)):
        return _MSG_AI_MODEL_INVALID_REQUEST
    if isinstance(e, (DeploymentNotFoundError, ResourceNotFoundError)):
        return _MSG_AI_MODEL_NOT_FOUND
    status = e.status_code
    if status == 401:
        return _MSG_AI_MODEL_AUTH_FAILED
    if status == 403:
        return _MSG_AI_MODEL_NO_PERMISSION
    if status == 404:
        return _MSG_AI_MODEL_NOT_FOUND
    if status == 422:
        return _MSG_AI_MODEL_INVALID_REQUEST
    if status == 429:
        return _MSG_AI_MODEL_RATE_LIMITED
    if status >= 500:
        return _MSG_AI_MODEL_INTERNAL_ERROR
    return _FALLBACK_MESSAGE


def _resolve_internal_error(e: Exception) -> str:
    if isinstance(e, OrchestratorExceedMaxIterationsException):
        return str(e)
    if isinstance(e, OrchestratorInitializationException):
        return _MSG_AI_MODEL_NOT_FOUND
    if isinstance(e, ToolsetNotFoundException):
        return "A required toolset could not be found. Please contact your administrator."
    if isinstance(e, ToolsetForbiddenException):
        return "Access to a required toolset is forbidden. Please contact your administrator."
    return _FALLBACK_MESSAGE


def _resolve_tool_error(e: ToolErrorException) -> str:
    # ToolErrorException may wrap a transport/status error that already has a dedicated message.
    if isinstance(e.__cause__, Exception):
        return resolve_exception_message(e.__cause__)
    return str(e)


def resolve_exception_message(e: Exception) -> str:
    """Return a safe, user-friendly message for any exception."""
    error: Exception = e
    if isinstance(error, ToolErrorException):
        return _resolve_tool_error(error)
    if isinstance(error, openai.OpenAIError):
        return _resolve_openai_error(error)
    if isinstance(error, httpx.HTTPError):
        return _resolve_httpx_error(error)
    if isinstance(error, AiDialHTTPException):
        return _resolve_aidial_error(error)
    return _resolve_internal_error(error)
