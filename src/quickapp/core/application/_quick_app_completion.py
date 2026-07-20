import logging
import time
import uuid
from collections import Counter

from aidial_sdk.chat_completion import ChatCompletion, Request, Response
from aidial_sdk.deployment.configuration import ConfigurationRequest, ConfigurationResponse
from aidial_sdk.exceptions import HTTPException as DialHTTPException
from injector import Injector, inject

from quickapp.common import InitializerType, StagedBaseTool
from quickapp.common.base_initializer import invoke_initializers
from quickapp.common.exceptions import ConfigResolutionException
from quickapp.common.lifecycle_logging import format_duration, format_event
from quickapp.common.perf_timer.perf_timer import PerformanceTimer
from quickapp.common.presentation_settings import PresentationSettings
from quickapp.config.application import ApplicationConfig
from quickapp.core.agent import Orchestrator
from quickapp.skills.agent_skills_provider import AgentSkillsProvider

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
        request_start = time.perf_counter()
        with response.create_single_choice() as choice:
            failed = False
            outcome = "completed"
            error_reference: str | None = None
            agent_invoker: Orchestrator | None = None
            try:
                request_context_setup = self.__injector.get(_RequestContextSetup)
                try:
                    await request_context_setup.setup_context(request, choice)
                except ConfigResolutionException:
                    # System prompt resolution is the only path that still raises;
                    # tool / toolset failures are skip-and-record inside the resolver.
                    failed = True
                    outcome = "failed"
                    self.__injector.get(_InitializationErrorHandler).handle_initialization_issues()
                    return
                self.__log_request_received(request)
                timer_service.add_milestone(self.__timer_period_name, "request context pre-init")
                await invoke_initializers(self.__injector, InitializerType.completion)
                timer_service.add_milestone(self.__timer_period_name, "initializers")
                await request_context_setup.setup_messages(request.messages)
                timer_service.add_milestone(self.__timer_period_name, "messages finalized")
                self.__injector.get(_InitializationErrorHandler).handle_initialization_issues()
                timer_service.add_milestone(self.__timer_period_name, "initialization issues")
                self.__log_request_initialized()
                agent_invoker = self.__injector.get(Orchestrator)  # type: ignore[type-abstract]
                await agent_invoker.invoke()
                outcome = agent_invoker.completion_kind
            except Exception as e:
                # Raises a DIAL protocol error; the SDK delivers it as a non-200 response
                # (or an SSE error chunk once the choice has opened the stream).
                failed = True
                outcome = "failed"
                error_reference = uuid.uuid4().hex[:8]
                self.__handle_exception(e, error_reference)
            finally:
                timer_service.stop_period(self.__timer_period_name)
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

    def __log_request_received(self, request: Request) -> None:
        app_config = self.__injector.get(ApplicationConfig)
        attachment_count = sum(
            len(message.custom_content.attachments)
            for message in request.messages
            if message.custom_content and message.custom_content.attachments
        )
        logger.info(
            format_event(
                "Request received",
                deployment=app_config.orchestrator.deployment.deployment_id,
                messages=len(request.messages),
                attachments=attachment_count,
            )
        )

    def __log_request_initialized(self) -> None:
        app_config = self.__injector.get(ApplicationConfig)
        tools = self.__injector.get(list[StagedBaseTool])
        tool_types = Counter(
            str(getattr(tool.tool_config, "type", "unknown")).removesuffix("-tool")
            for tool in tools
        )
        skill_count = len(self.__injector.get(AgentSkillsProvider).get_all_skills()) + len(
            app_config.skills or []
        )
        logger.info(
            format_event(
                "Request initialized",
                tools=len(tools),
                tool_types=tool_types or None,
                skills=skill_count,
                contexts=len(app_config.contexts),
            )
        )

    async def configuration(self, request: ConfigurationRequest) -> ConfigurationResponse:
        await self.__injector.get(_RequestContextSetup).setup_context(request)
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
