import logging
import time
from abc import ABC

from aidial_sdk.chat_completion import Message, Role
from injector import ProviderOf

from quickapp.agent_hooks._context_factory import HookContextFactory
from quickapp.agent_hooks._dispatcher import HookDispatcher
from quickapp.agent_hooks._handlers import hook_display_name, resolve_hook_tool_name
from quickapp.common.abstract.tool_call_result_enricher import ToolCallResultEnricher
from quickapp.common.hook_context.context import HookResult
from quickapp.common.synthetic_injection.injection_enums import InjectionFrequency
from quickapp.common.synthetic_injection.synthetic_tool_call_injector import (
    SyntheticToolCallInjector,
)
from quickapp.config.hooks import ToolCallHookConfig, TTLRefreshCondition

logger = logging.getLogger(__name__)


class _BaseConfigDrivenHook(ABC):
    """Abstract base for all config-driven hook variants."""


class _ConfigDrivenToolCallHook(_BaseConfigDrivenHook, SyntheticToolCallInjector):
    """``on_request_start`` seam adapter: injects the result of a hook as a synthetic pair.

    The hook itself runs through ``HookDispatcher``; this class owns only the injection
    mechanics (identity by template, TTL stamping, frequency). Instances are created per
    request, so the cached ``_last_result`` is never shared across requests.
    """

    def __init__(
        self,
        config: ToolCallHookConfig,
        dispatcher: HookDispatcher,
        context_factory: HookContextFactory,
        enrichers_provider: ProviderOf[list[ToolCallResultEnricher]] | None = None,
    ):
        super().__init__(enrichers_provider)
        self._config = config
        self._dispatcher = dispatcher
        self._context_factory = context_factory
        self._last_result: HookResult | None = None

    async def get_tool_name(self) -> str:
        return resolve_hook_tool_name(self._config)

    async def get_arguments(self) -> dict:
        return self._config.arguments

    async def get_call_arguments(self, messages: list[Message]) -> dict:
        if self._last_result is not None and self._last_result.arguments is not None:
            return self._last_result.arguments
        return await self.get_arguments()

    async def get_frequency(self, messages: list[Message]) -> InjectionFrequency:
        return self._config.frequency

    def make_call_id(
        self,
        tool_name: str,
        arguments: dict,
        content: str,
        ttl_expiry_seconds: int | None = None,
    ) -> str:
        rc = self._config.refresh_condition
        if isinstance(rc, TTLRefreshCondition) and ttl_expiry_seconds is None:
            ttl_expiry_seconds = int(time.time()) + rc.ttl_minutes * 60
        return super().make_call_id(tool_name, arguments, content, ttl_expiry_seconds)

    async def should_inject(self, messages: list[Message]) -> bool:
        rc = self._config.refresh_condition
        if not isinstance(rc, TTLRefreshCondition):
            return True
        tool_name = await self.get_tool_name()
        arguments = await self.get_arguments()
        id_prefix = self._make_call_id_prefix(tool_name, arguments)
        existing_call_id = next(
            (
                m.tool_call_id
                for m in reversed(messages)
                if m.role == Role.TOOL
                and m.tool_call_id is not None
                and m.tool_call_id.startswith(id_prefix)
            ),
            None,
        )
        if existing_call_id is None:
            return True
        expiry = self._parse_call_id_ttl_expiry(existing_call_id)
        if expiry is None:
            return True
        return int(time.time()) >= expiry

    async def get_content(self, messages: list[Message]) -> str | None:
        self._last_result = None
        try:
            context = self._context_factory.request_start(messages)
        except Exception:
            logger.exception(
                "Config-driven hook %r: failed to build context — skipping injection",
                hook_display_name(self._config),
            )
            return None
        result = await self._dispatcher.run_hook(self._config, context)
        self._last_result = result
        return result.content if result is not None else None
