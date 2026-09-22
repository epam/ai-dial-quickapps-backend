import logging
import time
import uuid

from aidial_sdk.chat_completion import ChatCompletion, Request, Response
from aidial_sdk.deployment.configuration import ConfigurationRequest, ConfigurationResponse
from aidial_sdk.exceptions import HTTPException as DialHTTPException
from injector import Injector, inject

from quickapp.common import InitializerType
from quickapp.common.base_initializer import invoke_initializers
from quickapp.common.lifecycle_logging import format_duration, format_event
from quickapp.common.perf_timer.perf_timer import PerformanceTimer
from quickapp.common.presentation_settings import PresentationSettings
from quickapp.core.agent import Orchestrator

from ._completion_inputs import CompletionInputs
from ._completion_runner import CompletionRunner
from ._exception_message_resolver import ResolvedError, resolve_exception
from ._messages_validator import validate_messages_shape
from ._proxy_settings import ProxySettings
from ._request_context_setup import _RequestContextSetup
from .configuration import Configuration

logger = logging.getLogger(__name__)

# Statuses safe to surface verbatim: client-attributable causes. Everything else — most
# importantly Core's retriable set (429/502/503/504), which for a single-upstream
# application Core cannot retry and would replace with a generic error — collapses to 500.
_CLIENT_ERROR_STATUS_CODES = frozenset({400, 401, 403, 404, 413, 422})


def _outgoing_status_code(resolved: ResolvedError) -> int:
    status = resolved.details.status_code
    if status in _CLIENT_ERROR_STATUS_CODES:
        return status
    return 500


# The _QuickAppCompletion class is a dependency-injected implementation of the ChatCompletion interface.
# It is the HTTP adapter: it turns the SDK request into `CompletionInputs`, hands them
# to `CompletionRunner`, and translates the outcome back into a DIAL response or error.
@inject
class _QuickAppCompletion(ChatCompletion):

    def __init__(
        self,
        injector: Injector,
        presentation_settings: PresentationSettings,
        proxy_settings: ProxySettings,
    ):
        self.__injector: Injector = injector
        self.__presentation_settings: PresentationSettings = presentation_settings
        self.__proxy_settings: ProxySettings = proxy_settings

    async def chat_completion(self, request: Request, response: Response) -> None:
        validate_messages_shape(request.messages)
        timer_service = self.__injector.get(PerformanceTimer)
        request_start = time.perf_counter()
        with response.create_single_choice() as choice:
            failed = False
            outcome = "completed"
            error_reference: str | None = None
            agent_invoker: Orchestrator | None = None
            try:
                inputs = await CompletionInputs.from_request(
                    request, choice, self.__proxy_settings.language_header
                )
                agent_invoker = await self.__injector.get(CompletionRunner).run(inputs)
                if agent_invoker is None:
                    failed = True
                    outcome = "failed"
                    return
                outcome = agent_invoker.completion_kind
            except Exception as e:
                # Raises a DIAL protocol error; the SDK delivers it as a non-200 response
                # (or an SSE error chunk once the choice has opened the stream).
                failed = True
                outcome = "failed"
                error_reference = uuid.uuid4().hex[:8]
                self.__handle_exception(e, error_reference)
            finally:
                logger.debug(
                    "Chat completion performance report:\n%s", timer_service.get_report_json()
                )
                logger.info(
                    format_event(
                        "Request completed",
                        outcome=outcome,
                        iterations=agent_invoker.iteration_count if agent_invoker else 0,
                        tool_calls=agent_invoker.total_tool_calls if agent_invoker else 0,
                        duration=format_duration(time.perf_counter() - request_start),
                        error_reference=error_reference,
                    )
                )
                # Skip the execution-time stage when an error is propagating, so no
                # spurious stage trails the delivered error.
                if not failed and self.__presentation_settings.show_execution_time_stage:
                    with choice.create_stage("Execution time") as stage:
                        stage.append_content(timer_service.get_report_md())

    async def configuration(self, request: ConfigurationRequest) -> ConfigurationResponse:
        inputs = await CompletionInputs.from_request(request)
        await self.__injector.get(_RequestContextSetup).setup_context(inputs)
        await invoke_initializers(self.__injector, InitializerType.configuration)
        if not self.__injector.binder.has_explicit_binding_for(list[Configuration]):
            return ConfigurationResponse()
        configurations = self.__injector.get(list[Configuration])
        return Configuration.from_list_of_configurations(configurations).to_configuration_response()

    @staticmethod
    def __handle_exception(e: Exception, error_reference: str) -> None:
        resolved = resolve_exception(e)
        logger.exception(
            "Exception %s occurred (error_reference=%s, retryable=%s, details=%s). %s",
            type(e),
            error_reference,
            resolved.retryable,
            resolved.details,
            e,
        )
        display = f"{resolved.message} (error reference: {error_reference})"
        status_code = _outgoing_status_code(resolved)
        # OpenAI-protocol convention when the upstream supplied no type: client-attributable
        # 4xx -> invalid_request_error, everything else -> runtime_error.
        default_type = "invalid_request_error" if status_code < 500 else "runtime_error"
        raise DialHTTPException(
            status_code=status_code,
            message=display,
            display_message=display,
            code=resolved.details.code,
            type=resolved.details.error_type or default_type,
        )
