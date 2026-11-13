import asyncio
import logging

from aidial_sdk.chat_completion import Attachment, Choice, Message, Role
from fastapi_injector import RequestScopeFactory
from injector import ProviderOf, inject
from pydantic import BaseModel, Field

from quickapp.common import (
    ACCEPT_LANGUAGE,
    DIAL_API_KEY,
    DIAL_BEARER,
    TIMEZONE_HEADER_VALUE,
    ForwardedHeaders,
)
from quickapp.common.abstract.completed_run import CompletedRun
from quickapp.common.abstract.completion_runner import BaseCompletionRunner
from quickapp.common.base_stage_wrapper import BaseStageWrapper
from quickapp.common.completion_inputs import CompletionInputs
from quickapp.common.deployment_usage import DeploymentUsage
from quickapp.common.exceptions import OrchestratorExceedMaxIterationsException
from quickapp.common.lifecycle_logging import format_event
from quickapp.common.message_text import message_text
from quickapp.common.messages_mixin import MessagesMixin
from quickapp.common.tool_allowlist import ToolAllowlist
from quickapp.config.application import ApplicationConfig
from quickapp.config.run_task import RunTaskConfig

from ._exceptions import TaskToolErrorException
from ._manifest_compiler import compile_task_manifest
from ._run_task_settings import RunTaskSettings
from ._task_output_sink import TaskOutputSink
from ._task_semaphore import TaskQueueTimeout, TaskSemaphore
from ._tool_catalogue import IMPLICIT_TASK_TOOL_NAMES
from ._tool_config import INHERIT_TOOLS

logger = logging.getLogger(__name__)


class TaskResult(BaseModel):
    """Everything a finished task hands back to the run_task tool."""

    answer: str
    attachments: list[Attachment] = Field(default_factory=list)
    usage: list[DeploymentUsage] = Field(default_factory=list)


def _task_timeout(settings: RunTaskSettings, config: RunTaskConfig) -> float:
    """The admin ceiling, which an app may shorten but never extend."""
    ceiling = settings.timeout_seconds
    declared = config.timeout_seconds
    return min(declared, ceiling) if declared is not None else ceiling


@inject
class TaskRunner:
    """Runs a delegated task in this process, inside its own DI request scope."""

    def __init__(
        self,
        runner_provider: ProviderOf[BaseCompletionRunner],
        messages_provider: ProviderOf[MessagesMixin],
        scope_factory: RequestScopeFactory,
        parent_config: ApplicationConfig,
        api_key: DIAL_API_KEY,
        bearer: DIAL_BEARER,
        forwarded_headers: ForwardedHeaders,
        accept_language: ACCEPT_LANGUAGE,
        timezone_header_value: TIMEZONE_HEADER_VALUE,
        config: RunTaskConfig,
        settings: RunTaskSettings,
        semaphore: TaskSemaphore,
    ) -> None:
        # Providers: both must resolve inside the child scope `__run` opens.
        self.__runner_provider = runner_provider
        self.__messages_provider = messages_provider
        self.__scope_factory = scope_factory
        self.__parent_config = parent_config
        self.__api_key = api_key
        self.__bearer = bearer
        self.__forwarded_headers = forwarded_headers
        self.__accept_language = accept_language
        self.__timezone_header_value = timezone_header_value
        self.__config = config
        self.__settings = settings
        self.__semaphore = semaphore

    async def run(
        self,
        prompt: str,
        allowlist: ToolAllowlist,
        stage_wrapper: BaseStageWrapper | None,
    ) -> TaskResult:
        # A dedicated task: the request scope key is a ContextVar, and asyncio copies
        # context per task, so the child scope cannot leak into the caller's.
        return await asyncio.create_task(self.__admit(prompt, allowlist, stage_wrapper))

    async def __admit(
        self,
        prompt: str,
        allowlist: ToolAllowlist,
        stage_wrapper: BaseStageWrapper | None,
    ) -> TaskResult:
        timeout = _task_timeout(self.__settings, self.__config)
        # The wait for a slot and the run each get the budget: queue time isn't
        # charged to the run, and the wait itself is bounded.
        try:
            async with self.__semaphore.hold(wait_seconds=timeout):
                deadline = asyncio.timeout(timeout)
                try:
                    async with deadline:
                        return await self.__run(prompt, allowlist, stage_wrapper)
                except TimeoutError:
                    # A TimeoutError raised inside the run is not the budget running out.
                    if not deadline.expired():
                        raise
                    raise TaskToolErrorException(
                        f"The task did not finish within its {timeout:g}s budget and was "
                        "stopped. Retry with a narrower task."
                    ) from None
        except TaskQueueTimeout:
            raise TaskToolErrorException(
                "Too many tasks are running right now. Try again later, or answer "
                "without a task."
            ) from None

    async def __run(
        self,
        prompt: str,
        allowlist: ToolAllowlist,
        stage_wrapper: BaseStageWrapper | None,
    ) -> TaskResult:
        manifest = compile_task_manifest(
            self.__parent_config, self.__config, explicit_tools=allowlist.names is not None
        )
        logger.info(
            format_event(
                "Running task",
                deployment=manifest.orchestrator.deployment.deployment_id,
                tools=(
                    INHERIT_TOOLS
                    if allowlist.names is None
                    else len(allowlist.names - IMPLICIT_TASK_TOOL_NAMES)
                ),
                max_iterations=manifest.orchestrator.max_iterations,
            )
        )

        # The task writes to a Choice like any request; its chunks are rendered into
        # the delegating agent's tool stage instead of being sent to a user.
        sink = TaskOutputSink(stage_wrapper)
        choice = Choice(sink, 0)
        choice.open()

        async with self.__scope_factory.create_scope():
            # The same lifecycle a user request runs — config resolution, initializers,
            # the initialization-issues check — against the compiled manifest.
            run = await self.__run_child(
                CompletionInputs(
                    api_key=self.__api_key,
                    bearer=self.__bearer,
                    application_config=manifest,
                    messages=[Message(role=Role.USER, content=prompt)],
                    choice=choice,
                    forwarded_headers=self.__forwarded_headers,
                    # The task serves the same user: same locale, same time zone.
                    accept_language=self.__accept_language,
                    timezone_header_value=self.__timezone_header_value,
                    tool_allowlist=allowlist,
                    is_task=True,
                )
            )
            if run is None:
                raise TaskToolErrorException("The task's configuration could not be resolved.")
            return TaskResult(
                answer=self.__final_answer(self.__messages_provider.get()),
                attachments=sink.attachments,
                usage=run.usage_statistics,
            )

    async def __run_child(self, inputs: CompletionInputs) -> CompletedRun | None:
        try:
            return await self.__runner_provider.get().run(inputs)
        except OrchestratorExceedMaxIterationsException:
            raise TaskToolErrorException(
                "The task ran out of its max_iterations budget before finishing. "
                "Retry with a narrower task."
            ) from None

    @staticmethod
    def __final_answer(context: MessagesMixin) -> str:
        for message in reversed(context.messages):
            if message.role == Role.ASSISTANT and not message.tool_calls:
                # Files and images travel back on `TaskResult.attachments`, collected
                # by `TaskOutputSink`; the answer itself is the joined text.
                text = message_text(message).strip()
                if text:
                    return text
                break
        # An empty reply is stored as " ": fail rather than hand the LLM an empty
        # "successful" result it would answer from.
        raise TaskToolErrorException("The task finished without an answer.")
