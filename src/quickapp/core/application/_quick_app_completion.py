import logging
import uuid

from aidial_sdk.chat_completion import ChatCompletion, Request, Response
from aidial_sdk.deployment.configuration import ConfigurationRequest, ConfigurationResponse
from aidial_sdk.exceptions import HTTPException as DialHTTPException
from injector import Injector, inject

from quickapp.common import InitializerType
from quickapp.common.base_initializer import invoke_initializers
from quickapp.common.exceptions import ConfigResolutionException
from quickapp.common.perf_timer.perf_timer import PerformanceTimer
from quickapp.common.presentation_settings import PresentationSettings
from quickapp.core.agent import Orchestrator

from ._exception_message_resolver import ResolvedError, resolve_exception
from ._initialization_error_handler import _InitializationErrorHandler
from ._messages_validator import validate_messages_shape
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
# It handles chat completion and configuration requests in a FastAPI application by:
# - Setting up per-request context (API key, app config, messages, response choice)
# - Invoking initializers of other modules
# - Delegating message processing to an agent
# - Returning application-specific configuration if available
@inject
class _QuickAppCompletion(ChatCompletion):

    def __init__(
        self,
        injector: Injector,
        presentation_settings: PresentationSettings,
    ):
        self.__injector: Injector = injector
        self.__presentation_settings: PresentationSettings = presentation_settings
        self.__timer_period_name = "chat_completion"

    async def chat_completion(self, request: Request, response: Response) -> None:
        validate_messages_shape(request.messages)
        timer_service = self.__injector.get(PerformanceTimer)
        timer_service.start_period(self.__timer_period_name, level=1)
        with response.create_single_choice() as choice:
            failed = False
            try:
                request_context_setup = self.__injector.get(_RequestContextSetup)
                try:
                    await request_context_setup.setup_context(request, choice)
                except ConfigResolutionException:
                    # System prompt resolution is the only path that still raises;
                    # tool / toolset failures are skip-and-record inside the resolver.
                    self.__injector.get(_InitializationErrorHandler).handle_initialization_issues()
                    return
                timer_service.add_milestone(self.__timer_period_name, "request context pre-init")
                await invoke_initializers(self.__injector, InitializerType.completion)
                timer_service.add_milestone(self.__timer_period_name, "initializers")
                await request_context_setup.setup_messages(request.messages)
                timer_service.add_milestone(self.__timer_period_name, "messages finalized")
                self.__injector.get(_InitializationErrorHandler).handle_initialization_issues()
                timer_service.add_milestone(self.__timer_period_name, "initialization issues")
                agent_invoker = self.__injector.get(Orchestrator)  # type: ignore[type-abstract]
                await agent_invoker.invoke()
            except Exception as e:
                # Raises a DIAL protocol error; the SDK delivers it as a non-200 response
                # (or an SSE error chunk once the choice has opened the stream).
                failed = True
                self.__handle_exception(e)
            finally:
                timer_service.stop_period(self.__timer_period_name)
                logger.debug(
                    "Chat completion performance report:\n%s", timer_service.get_report_json()
                )
                # Skip the execution-time stage when an error is propagating, so no
                # spurious stage trails the delivered error.
                if not failed and self.__presentation_settings.show_execution_time_stage:
                    with choice.create_stage("Execution time") as stage:
                        stage.append_content(timer_service.get_report_md())

    async def configuration(self, request: ConfigurationRequest) -> ConfigurationResponse:
        await self.__injector.get(_RequestContextSetup).setup_context(request)
        await invoke_initializers(self.__injector, InitializerType.configuration)
        if not self.__injector.binder.has_explicit_binding_for(list[Configuration]):
            return ConfigurationResponse()
        configurations = self.__injector.get(list[Configuration])
        return Configuration.from_list_of_configurations(configurations).to_configuration_response()

    @staticmethod
    def __handle_exception(e: Exception) -> None:
        error_reference = uuid.uuid4().hex[:8]
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
        raise DialHTTPException(
            status_code=_outgoing_status_code(resolved),
            message=display,
            display_message=display,
            code=resolved.details.code,
            type=resolved.details.error_type or "runtime_error",
        )
