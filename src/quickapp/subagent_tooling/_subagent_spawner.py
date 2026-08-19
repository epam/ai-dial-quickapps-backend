import asyncio
import logging

from aidial_sdk.chat_completion import Choice, Message, Role
from fastapi_injector import RequestScopeFactory
from injector import Injector, inject

from quickapp.common import DIAL_API_KEY, DIAL_BEARER, ForwardedHeaders
from quickapp.common.base_initializer import InitializerType, invoke_initializers
from quickapp.config.application import ApplicationConfig
from quickapp.config.subagent import SubagentConfig
from quickapp.core.agent.orchestrator import Orchestrator
from quickapp.core.application._request_context import _RequestContext
from quickapp.core.application._request_context_setup import _RequestContextSetup

from ._manifest_compiler import compile_subagent_manifest

logger = logging.getLogger(__name__)


def _headless_choice() -> Choice:
    """A Choice whose chunks go nowhere.

    SPIKE ONLY. The design calls for an output-sink abstraction so the orchestrator
    stops depending on Choice at all; this stand-in lets the loop run unmodified by
    draining into a queue nobody consumes.
    """
    choice = Choice(asyncio.Queue(), 0)
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

            return self.__final_answer(context)

    @staticmethod
    def __final_answer(context: _RequestContext) -> str:
        for message in reversed(context.messages):
            if message.role == Role.ASSISTANT and not message.tool_calls:
                return message.content or ""
        return ""
