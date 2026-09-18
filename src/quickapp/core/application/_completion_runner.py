import logging
from collections import Counter

from injector import Injector, inject

from quickapp.common import InitializerType, StagedBaseTool
from quickapp.common.base_initializer import invoke_initializers
from quickapp.common.exceptions import ConfigResolutionException
from quickapp.common.lifecycle_logging import format_event
from quickapp.common.perf_timer.perf_timer import PerformanceTimer
from quickapp.config.application import ApplicationConfig
from quickapp.core.agent import Orchestrator
from quickapp.skills.agent_skills_provider import AgentSkillsProvider

from ._completion_inputs import CompletionInputs
from ._initialization_error_handler import _InitializationErrorHandler
from ._request_context_setup import _RequestContextSetup

logger = logging.getLogger(__name__)

TIMER_PERIOD = "chat_completion"


@inject
class CompletionRunner:
    """One completion lifecycle in the current request scope:
    context → initializers → messages → initialization issues → orchestrator.

    The HTTP handler and the subagent spawner both run through here, so a spoke
    gets the same config resolution and initialization checks as a user request.
    """

    def __init__(
        self,
        injector: Injector,
        context_setup: _RequestContextSetup,
        error_handler: _InitializationErrorHandler,
        perf_timer: PerformanceTimer,
    ) -> None:
        self.__injector = injector
        self.__context_setup = context_setup
        self.__error_handler = error_handler
        self.__perf_timer = perf_timer

    async def run(self, inputs: CompletionInputs) -> Orchestrator | None:
        """Run the orchestrator; ``None`` when the manifest could not be resolved.

        In that case the issue has already been rendered to the choice — there is no
        LLM to call, so the run ends without an error of its own. The run owns the
        ``chat_completion`` timer period; callers read the report once this returns.
        """
        self.__perf_timer.start_period(TIMER_PERIOD, level=1)
        try:
            return await self.__run(inputs)
        finally:
            self.__perf_timer.stop_period(TIMER_PERIOD)

    async def __run(self, inputs: CompletionInputs) -> Orchestrator | None:
        try:
            await self.__context_setup.setup_context(inputs)
        except ConfigResolutionException:
            # System prompt resolution is the only path that still raises;
            # tool / toolset failures are skip-and-record inside the resolver.
            self.__error_handler.handle_initialization_issues()
            return None
        self.__log_request_received(inputs)
        self.__perf_timer.add_milestone(TIMER_PERIOD, "request context pre-init")
        await invoke_initializers(self.__injector, InitializerType.completion)
        self.__perf_timer.add_milestone(TIMER_PERIOD, "initializers")
        await self.__context_setup.setup_messages(inputs.messages)
        self.__perf_timer.add_milestone(TIMER_PERIOD, "messages finalized")
        self.__error_handler.handle_initialization_issues()
        self.__perf_timer.add_milestone(TIMER_PERIOD, "initialization issues")
        self.__log_request_initialized()
        orchestrator = self.__injector.get(Orchestrator)  # type: ignore[type-abstract]
        await orchestrator.invoke()
        return orchestrator

    def __log_request_received(self, inputs: CompletionInputs) -> None:
        app_config = self.__injector.get(ApplicationConfig)
        attachment_count = sum(
            len(message.custom_content.attachments)
            for message in inputs.messages
            if message.custom_content and message.custom_content.attachments
        )
        logger.info(
            format_event(
                "Request received",
                deployment=app_config.orchestrator.deployment.deployment_id,
                messages=len(inputs.messages),
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
