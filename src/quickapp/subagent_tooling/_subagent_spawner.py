import asyncio
import logging
from typing import Any

from aidial_sdk.chat_completion import Attachment, Choice, Message, Role
from aidial_sdk.chat_completion.request import MessageContentTextPart
from fastapi_injector import RequestScopeFactory
from injector import Injector, inject
from pydantic import BaseModel, ConfigDict, Field

from quickapp.common import DIAL_API_KEY, DIAL_BEARER, ForwardedHeaders
from quickapp.common.base_initializer import InitializerType, invoke_initializers
from quickapp.common.base_stage_wrapper import BaseStageWrapper
from quickapp.config.application import ApplicationConfig
from quickapp.config.subagent import SubagentsConfig
from quickapp.core.agent.orchestrator import Orchestrator
from quickapp.core.application._request_context import _RequestContext
from quickapp.core.application._request_context_setup import _RequestContextSetup

from ._exceptions import SubagentToolErrorException
from ._manifest_compiler import compile_subagent_manifest
from ._subagent_output_sink import SubagentOutputSink
from ._subagent_settings import SpawnSemaphore, SubagentSettings
from ._tool_config import TASK_TOOL_NAME

logger = logging.getLogger(__name__)


class SpawnResult(BaseModel):
    """Everything a finished spoke hands back to the coordinator's tool."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    answer: str
    attachments: list[Attachment] = Field(default_factory=list)


def _as_text(content: str | list[Any] | None) -> str:
    """Flatten a message's content down to the text a tool result can carry."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    return "".join(part.text for part in content if isinstance(part, MessageContentTextPart))


@inject
class SubagentSpawner:
    """Runs a subagent in this process, inside its own DI request scope."""

    def __init__(
        self,
        injector: Injector,
        scope_factory: RequestScopeFactory,
        parent_config: ApplicationConfig,
        api_key: DIAL_API_KEY,
        bearer: DIAL_BEARER,
        forwarded_headers: ForwardedHeaders,
        config: SubagentsConfig,
        settings: SubagentSettings,
        semaphore: SpawnSemaphore,
    ) -> None:
        self.__injector = injector
        self.__scope_factory = scope_factory
        self.__parent_config = parent_config
        self.__api_key = api_key
        self.__bearer = bearer
        self.__forwarded_headers = forwarded_headers
        self.__config = config
        self.__settings = settings
        self.__semaphore = semaphore

    async def spawn(
        self,
        task: str,
        tool_sets: list[str],
        stage_wrapper: BaseStageWrapper | None = None,
    ) -> SpawnResult:
        timeout = self.__timeout()
        # Run in a dedicated task: the request scope key is a ContextVar, and asyncio
        # copies context per task, so the child scope cannot leak into the caller's.
        spawn = asyncio.create_task(self.__run(task, tool_sets, stage_wrapper))
        try:
            return await asyncio.wait_for(spawn, timeout)
        except TimeoutError:
            # A truncated spoke has no answer to give, so this must reach the
            # coordinator as a tool error it can act on rather than as silence.
            raise SubagentToolErrorException(
                tool_name=TASK_TOOL_NAME,
                error_message=(
                    f"The subagent did not finish within its {timeout:g}s budget and was "
                    "stopped. Retry with a narrower task."
                ),
            ) from None

    def __timeout(self) -> float:
        """The admin ceiling, which an app may shorten but never extend."""
        ceiling = self.__settings.timeout_seconds
        declared = self.__config.timeout_seconds
        return min(declared, ceiling) if declared is not None else ceiling

    async def __run(
        self,
        task: str,
        tool_sets: list[str],
        stage_wrapper: BaseStageWrapper | None,
    ) -> SpawnResult:
        manifest = compile_subagent_manifest(self.__parent_config, self.__config, tool_sets)
        logger.info(
            "Spawning subagent: deployment=%s, tool_sets=%d, max_iterations=%d",
            manifest.orchestrator.deployment.deployment_id,
            len(manifest.tool_sets),
            manifest.orchestrator.max_iterations,
        )

        # The spoke writes to a Choice like any request; this one's chunks are rendered
        # into the coordinator's tool stage instead of being sent to a user.
        sink = SubagentOutputSink(stage_wrapper)
        choice = Choice(sink, 0)
        choice.open()

        async with self.__semaphore.hold(), self.__scope_factory.create_scope():
            context = self.__injector.get(_RequestContext)
            context.api_key = self.__api_key
            context.bearer = self.__bearer
            context.forwarded_headers = self.__forwarded_headers
            context.application_config = manifest
            context.choice = choice

            setup = self.__injector.get(_RequestContextSetup)
            await invoke_initializers(self.__injector, InitializerType.completion)
            await setup.setup_messages([Message(role=Role.USER, content=task)])

            orchestrator = self.__injector.get(Orchestrator)  # type: ignore[type-abstract]
            await orchestrator.invoke()

            return SpawnResult(
                answer=self.__final_answer(context),
                attachments=sink.attachments,
            )

    @staticmethod
    def __final_answer(context: _RequestContext) -> str:
        for message in reversed(context.messages):
            if message.role == Role.ASSISTANT and not message.tool_calls:
                # `content` widens to a list of content parts for multimodal messages.
                # A spoke's *answer* is one string, so join the text parts; anything the
                # spoke produced as a file or image travels back on `SpawnResult`
                # instead, collected from its choice by `SubagentOutputSink`.
                text = _as_text(message.content)
                if text:
                    return text
                break
        # A spoke that exhausted its iteration budget mid-tool-loop leaves no final
        # message. Returning "" here would reach the coordinator's LLM as a successful
        # tool result and it would answer from nothing; fail the call instead.
        raise SubagentToolErrorException(
            tool_name=TASK_TOOL_NAME,
            error_message=(
                "The subagent produced no answer. It most likely exhausted its "
                "max_iterations budget before finishing. Retry with a narrower task."
            ),
        )
