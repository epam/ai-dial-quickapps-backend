import logging
from abc import ABC

from aidial_sdk.chat_completion import Message
from injector import ProviderOf

from quickapp.common.abstract.tool_call_result_enricher import ToolCallResultEnricher
from quickapp.common.staged_base_tool import StagedBaseTool
from quickapp.common.synthetic_injection.injection_enums import InjectionFrequency
from quickapp.common.synthetic_injection.staged_tool_synthetic_injector import (
    StagedToolSyntheticInjector,
)
from quickapp.common.utils import sanitize_toolname
from quickapp.config.hooks import ToolCallHookConfig

logger = logging.getLogger(__name__)


class _BaseConfigDrivenHook(ABC):
    """Abstract base for all config-driven hook variants."""


def resolve_hook_tool_name(config: ToolCallHookConfig) -> str:
    if config.toolset_name is not None:
        return sanitize_toolname(f"{config.toolset_name}_{config.tool_name}")
    return config.tool_name


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
        return resolve_hook_tool_name(self._config)

    async def get_arguments(self) -> dict:
        return self._config.arguments

    async def get_frequency(self, messages: list[Message]) -> InjectionFrequency:
        return self._config.frequency

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
