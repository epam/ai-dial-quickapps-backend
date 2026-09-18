import asyncio
import logging
from typing import Any

from aidial_sdk.chat_completion import Attachment, Choice, Message, Role
from aidial_sdk.chat_completion.request import MessageContentTextPart
from fastapi_injector import RequestScopeFactory
from injector import Injector, inject
from pydantic import BaseModel, ConfigDict, Field

from quickapp.common import DIAL_API_KEY, DIAL_BEARER, ForwardedHeaders
from quickapp.common.base_stage_wrapper import BaseStageWrapper
from quickapp.common.lifecycle_logging import format_event
from quickapp.common.messages_mixin import MessagesMixin
from quickapp.config.application import ApplicationConfig
from quickapp.config.subagent import SubagentConfig, SubagentsConfig
from quickapp.core.application import CompletionInputs, CompletionRunner

from ._exceptions import SubagentToolErrorException, SubagentToolSetResolutionError
from ._manifest_compiler import compile_subagent_manifest
from ._subagent_output_sink import SubagentOutputSink
from ._subagent_settings import SpawnSemaphore, SubagentSettings

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
        subagent: SubagentConfig,
        task: str,
        stage_wrapper: BaseStageWrapper | None = None,
    ) -> SpawnResult:
        timeout = self.__timeout()
        # Run in a dedicated task: the request scope key is a ContextVar, and asyncio
        # copies context per task, so the child scope cannot leak into the caller's.
        spawn = asyncio.create_task(self.__run(subagent, task, stage_wrapper))
        try:
            return await asyncio.wait_for(spawn, timeout)
        except TimeoutError:
            # A truncated spoke has no answer to give, so this must reach the
            # coordinator as a tool error it can act on rather than as silence.
            raise SubagentToolErrorException(
                tool_name=subagent.name,
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
        subagent: SubagentConfig,
        task: str,
        stage_wrapper: BaseStageWrapper | None,
    ) -> SpawnResult:
        try:
            manifest = compile_subagent_manifest(self.__parent_config, subagent)
        except SubagentToolSetResolutionError as e:
            # Same path as an answerless spoke: the LLM sees why and can reword.
            raise SubagentToolErrorException(tool_name=subagent.name, error_message=str(e)) from e
        logger.info(
            format_event(
                "Spawning subagent",
                subagent=subagent.name,
                deployment=manifest.orchestrator.deployment.deployment_id,
                tool_sets=len(manifest.tool_sets),
                max_iterations=manifest.orchestrator.max_iterations,
            )
        )

        # The spoke writes to a Choice like any request; this one's chunks are rendered
        # into the coordinator's tool stage instead of being sent to a user.
        sink = SubagentOutputSink(stage_wrapper)
        choice = Choice(sink, 0)
        choice.open()

        async with self.__semaphore.hold(), self.__scope_factory.create_scope():
            # The same lifecycle a user request runs — config resolution, initializers,
            # the initialization-issues check — against the compiled manifest.
            orchestrator = await self.__injector.get(CompletionRunner).run(
                CompletionInputs(
                    api_key=self.__api_key,
                    bearer=self.__bearer,
                    application_config=manifest,
                    messages=[Message(role=Role.USER, content=task)],
                    choice=choice,
                    forwarded_headers=self.__forwarded_headers,
                )
            )
            if orchestrator is None:
                raise SubagentToolErrorException(
                    tool_name=subagent.name,
                    error_message="The subagent's configuration could not be resolved.",
                )
            return SpawnResult(
                answer=self.__final_answer(self.__injector.get(MessagesMixin), subagent.name),
                attachments=sink.attachments,
            )

    @staticmethod
    def __final_answer(context: MessagesMixin, subagent_name: str) -> str:
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
            tool_name=subagent_name,
            error_message=(
                "The subagent produced no answer. It most likely exhausted its "
                "max_iterations budget before finishing. Retry with a narrower task."
            ),
        )
