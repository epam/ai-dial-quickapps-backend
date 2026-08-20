import asyncio
import logging
from typing import Any

from aidial_sdk.chat_completion import Choice, Message, Role
from aidial_sdk.chat_completion.request import MessageContentTextPart
from fastapi_injector import RequestScopeFactory
from injector import Injector, inject

from quickapp.common import DIAL_API_KEY, DIAL_BEARER, ForwardedHeaders
from quickapp.common.base_initializer import InitializerType, invoke_initializers
from quickapp.config.application import ApplicationConfig
from quickapp.config.subagent import SubagentConfig
from quickapp.core.agent.orchestrator import Orchestrator
from quickapp.core.application._request_context import _RequestContext
from quickapp.core.application._request_context_setup import _RequestContextSetup

from ._exceptions import SubagentToolErrorException
from ._manifest_compiler import compile_subagent_manifest

logger = logging.getLogger(__name__)


class _DiscardingQueue(asyncio.Queue):  # type: ignore[type-arg]
    """A chunk queue that drops everything put into it.

    ``Choice.send_chunk`` calls ``put_nowait``; overriding it discards the spoke's
    chunks where they are produced, so none accumulate for the life of a spawn.
    """

    def put_nowait(self, item: object) -> None:
        return


def _as_text(content: str | list[Any] | None) -> str:
    """Flatten a message's content down to the text a tool result can carry."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    return "".join(part.text for part in content if isinstance(part, MessageContentTextPart))


def _headless_choice() -> Choice:
    """A Choice whose chunks go nowhere.

    A subagent has no user conversation to stream into, but ``Orchestrator`` writes
    to a ``Choice`` directly. This stand-in lets the loop run unmodified.

    Known limitation: everything the orchestrator writes to the choice is dropped
    rather than forwarded to the coordinator. That is harmless for streamed content
    (the final answer is read back off ``_RequestContext.messages``) and for
    ``set_state`` (subagents are stateless), but **attachments a subagent produces
    are lost** — only text crosses back. Lifting that requires decoupling the
    orchestrator from ``Choice``.
    """
    choice = Choice(_DiscardingQueue(), 0)
    choice.open()
    return choice


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
    ) -> None:
        self.__injector = injector
        self.__scope_factory = scope_factory
        self.__parent_config = parent_config
        self.__api_key = api_key
        self.__bearer = bearer
        self.__forwarded_headers = forwarded_headers

    async def spawn(self, subagent: SubagentConfig, task: str) -> str:
        # Run in a dedicated task: the request scope key is a ContextVar, and asyncio
        # copies context per task, so the child scope cannot leak into the caller's.
        return await asyncio.create_task(self.__run(subagent, task))

    async def __run(self, subagent: SubagentConfig, task: str) -> str:
        manifest = compile_subagent_manifest(self.__parent_config, subagent)
        logger.info(
            "Spawning subagent %s: deployment=%s, tool_sets=%d, max_iterations=%d",
            subagent.name,
            manifest.orchestrator.deployment.deployment_id,
            len(manifest.tool_sets),
            manifest.orchestrator.max_iterations,
        )

        async with self.__scope_factory.create_scope():
            context = self.__injector.get(_RequestContext)
            context.api_key = self.__api_key
            context.bearer = self.__bearer
            context.forwarded_headers = self.__forwarded_headers
            context.application_config = manifest
            context.choice = _headless_choice()

            setup = self.__injector.get(_RequestContextSetup)
            await invoke_initializers(self.__injector, InitializerType.completion)
            await setup.setup_messages([Message(role=Role.USER, content=task)])

            orchestrator = self.__injector.get(Orchestrator)  # type: ignore[type-abstract]
            await orchestrator.invoke()

            return self.__final_answer(context, subagent.name)

    @staticmethod
    def __final_answer(context: _RequestContext, subagent_name: str) -> str:
        for message in reversed(context.messages):
            if message.role == Role.ASSISTANT and not message.tool_calls:
                # `content` widens to a list of content parts for multimodal messages.
                # A spoke returns one string to its caller, so join the text parts and
                # let anything else (images, files) fall through to the error below —
                # the tool result has no channel to carry them until the output sink
                # lands. See `_headless_choice`.
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
