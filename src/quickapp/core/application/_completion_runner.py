import logging
from collections import Counter

from injector import ProviderOf, inject

from quickapp.common import StagedBaseTool
from quickapp.common.abstract.completion_runner import BaseCompletionRunner
from quickapp.common.base_initializer import CompletionInitializer, run_initializers
from quickapp.common.completion_inputs import CompletionInputs
from quickapp.common.exceptions import ConfigResolutionException, OrchestratorSystemPromptException
from quickapp.common.lifecycle_logging import format_event
from quickapp.common.model_hidden_tool import ModelHiddenTool
from quickapp.common.perf_timer.perf_timer import PerformanceTimer
from quickapp.config.application import ApplicationConfig
from quickapp.core.agent import Orchestrator
from quickapp.skills.registry.agent_skills_provider import AgentSkillsProvider

from ._initialization_error_handler import _InitializationErrorHandler
from ._request_context_setup import _RequestContextSetup

logger = logging.getLogger(__name__)

TIMER_PERIOD = "chat_completion"


@inject
class CompletionRunner(BaseCompletionRunner):
    """One completion lifecycle in the current request scope:
    context → initializers → messages → initialization issues → orchestrator.

    The HTTP handler and the task runner both run through here, so a delegated task
    gets the same config resolution and initialization checks as a user request.
    """

    def __init__(
        self,
        context_setup: _RequestContextSetup,
        error_handler: _InitializationErrorHandler,
        perf_timer: PerformanceTimer,
        orchestrator_provider: ProviderOf[Orchestrator],
        config_provider: ProviderOf[ApplicationConfig],
        tools_provider: ProviderOf[list[StagedBaseTool]],
        model_hidden_tools_provider: ProviderOf[list[ModelHiddenTool]],
        skills_provider: ProviderOf[AgentSkillsProvider],
        initializers_provider: ProviderOf[list[CompletionInitializer]],
    ) -> None:
        # Providers, not instances: these resolve against the manifest that
        # `setup_context` installs, so they must be fetched after it runs.
        self.__orchestrator_provider = orchestrator_provider
        self.__config_provider = config_provider
        self.__tools_provider = tools_provider
        self.__model_hidden_tools_provider = model_hidden_tools_provider
        self.__skills_provider = skills_provider
        self.__initializers_provider = initializers_provider
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
            self.__log_request_received(inputs)
            self.__perf_timer.add_milestone(TIMER_PERIOD, "request context pre-init")
            await run_initializers(self.__initializers_provider.get())
        except (ConfigResolutionException, OrchestratorSystemPromptException):
            # System prompt resolution is the only path that still raises (predefined in
            # setup_context, `dial` in its initializer); tool / toolset failures are
            # skip-and-record.
            self.__error_handler.handle_initialization_issues()
            return None
        self.__perf_timer.add_milestone(TIMER_PERIOD, "initializers")
        await self.__context_setup.setup_messages(inputs.messages)
        self.__perf_timer.add_milestone(TIMER_PERIOD, "messages finalized")
        self.__error_handler.handle_initialization_issues()
        self.__perf_timer.add_milestone(TIMER_PERIOD, "initialization issues")
        self.__log_request_initialized()
        orchestrator = self.__orchestrator_provider.get()
        await orchestrator.invoke()
        self.__perf_timer.add_milestone(TIMER_PERIOD, "orchestrator_invoked")
        return orchestrator

    def __log_request_received(self, inputs: CompletionInputs) -> None:
        app_config = self.__config_provider.get()
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
        app_config = self.__config_provider.get()
        tools = self.__tools_provider.get()
        model_hidden_tools = self.__model_hidden_tools_provider.get()
        tool_types = Counter(
            str(getattr(tool.tool_config, "type", "unknown")).removesuffix("-tool")
            for tool in tools
        )
        skill_count = len(self.__skills_provider.get().get_all_skills()) + len(
            app_config.skills or []
        )
        logger.info(
            format_event(
                "Request initialized",
                tools=len(tools),
                tool_types=tool_types or None,
                model_hidden_tools=len(model_hidden_tools) or None,
                skills=skill_count,
                contexts=len(app_config.contexts),
            )
        )
