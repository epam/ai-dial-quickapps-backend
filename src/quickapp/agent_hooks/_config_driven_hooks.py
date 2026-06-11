import logging
import time
from abc import ABC

from aidial_sdk.chat_completion import Message, Role
from injector import ProviderOf

from quickapp.common.abstract.tool_call_result_enricher import ToolCallResultEnricher
from quickapp.common.staged_base_tool import StagedBaseTool
from quickapp.common.synthetic_injection.injection_enums import InjectionFrequency
from quickapp.common.synthetic_injection.staged_tool_synthetic_injector import (
    StagedToolSyntheticInjector,
)
from quickapp.common.utils import sanitize_toolname
from quickapp.config.hooks import ToolCallHookConfig, TTLRefreshCondition

logger = logging.getLogger(__name__)


class _BaseConfigDrivenHook(ABC):
    """Abstract base for all config-driven hook variants."""


class _ConfigDrivenToolCallHook(_BaseConfigDrivenHook, StagedToolSyntheticInjector):
    """Resolves a StagedBaseTool by name, calls it, and injects the result pair.

    Explicit __init__ bypasses @inject on StagedToolSyntheticInjector.__init__
    so AgentHooksModule can instantiate this class manually.
    """

    def __init__(
        self,
        tools: list[StagedBaseTool],
        config: ToolCallHookConfig,
        enrichers_provider: ProviderOf[list[ToolCallResultEnricher]] | None = None,
    ):
        super().__init__(tools, enrichers_provider)
        self._config = config

    async def get_tool_name(self) -> str:
        if self._config.toolset_name is not None:
            return sanitize_toolname(f"{self._config.toolset_name}_{self._config.tool_name}")
        return self._config.tool_name

    async def get_arguments(self) -> dict:
        return self._config.arguments

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
        try:
            return await super().get_content(messages)
        except Exception:
            logger.exception(
                "Config-driven hook %r: error fetching content for tool %r — skipping injection",
                self._config.name or self._config.tool_name,
                self._config.tool_name,
            )
            return None
