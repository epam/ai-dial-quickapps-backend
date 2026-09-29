import logging
from abc import ABC

from aidial_sdk.chat_completion import Message
from injector import ProviderOf, inject

from quickapp.common.abstract.tool_call_result_enricher import ToolCallResultEnricher
from quickapp.common.staged_base_tool import StagedBaseTool
from quickapp.common.synthetic_injection.staged_tool_lookup import (
    build_staged_tool_index,
    find_staged_tool,
)
from quickapp.common.synthetic_injection.synthetic_tool_call_injector import (
    SyntheticToolCallInjector,
)
from quickapp.config.application import StageDisplayLevel

logger = logging.getLogger(__name__)

_ARUN_SYNTHETIC_CALL_ID = "synthetic_injection_probe"


class StagedToolSyntheticInjector(SyntheticToolCallInjector, ABC):
    """Provides `get_content` by locating a `StagedBaseTool` by its sanitized
    OpenAI function name and calling `tool.arun()` with the declared arguments."""

    stage_level: StageDisplayLevel = StageDisplayLevel.DEBUG
    """How visible the injected call's stage is. Defaults to DEBUG, which hides it:
    an injection the user did not ask for should not look like work they requested.
    A subclass acting on an explicit user action overrides it with INFO."""

    @inject
    def __init__(
        self,
        tools: list[StagedBaseTool],
        enrichers_provider: ProviderOf[list[ToolCallResultEnricher]] | None = None,
    ):
        super().__init__(enrichers_provider)
        self.__tools = build_staged_tool_index(tools)

    async def get_content(self, messages: list[Message]) -> str | None:
        tool_name = await self.get_tool_name()
        tool = find_staged_tool(self.__tools, tool_name, logger, "StagedToolSyntheticInjector")
        if tool is None:
            return None
        arguments = await self.get_arguments()
        result = await tool.arun(_ARUN_SYNTHETIC_CALL_ID, stage_level=self.stage_level, **arguments)
        return result.content
