import logging

from aidial_sdk.chat_completion import ChatCompletion, Request, Response
from aidial_sdk.chat_completion.choice import Choice
from aidial_sdk.deployment.configuration import ConfigurationRequest, ConfigurationResponse
from injector import Injector, inject

from quickapp.common import InitializerType
from quickapp.common.base_initializer import invoke_initializers
from quickapp.common.exceptions import ConfigResolutionException
from quickapp.common.perf_timer.perf_timer import PerformanceTimer
from quickapp.common.presentation_settings import PresentationSettings
from quickapp.core.agent import Orchestrator

from ._exception_message_resolver import resolve_exception_message
from ._initialization_error_handler import _InitializationErrorHandler
from ._messages_validator import validate_messages_shape
from ._request_context_setup import _RequestContextSetup
from .configuration import Configuration

logger = logging.getLogger(__name__)


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
                self.__handle_exception(choice, e)
            finally:
                timer_service.stop_period(self.__timer_period_name)
                logger.debug(
                    "Chat completion performance report:\n%s", timer_service.get_report_json()
                )
                if self.__presentation_settings.show_execution_time_stage:
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
    def __handle_exception(choice: Choice, e: Exception) -> None:
        logger.exception("Exception %s occurred. %s", type(e), e)
        choice.append_content(resolve_exception_message(e))
