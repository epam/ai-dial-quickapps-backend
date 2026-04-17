import logging
from abc import ABC

from aidial_sdk.chat_completion import Message
from injector import inject

from quickapp.common.staged_base_tool import StagedBaseTool
from quickapp.common.synthetic_injection.synthetic_tool_call_injector import (
    SyntheticToolCallInjector,
)

logger = logging.getLogger(__name__)

_ARUN_SYNTHETIC_CALL_ID = "synthetic_injection_probe"


class StagedToolSyntheticInjector(SyntheticToolCallInjector, ABC):
    """Provides `get_content` by locating a `StagedBaseTool` by its sanitized
    OpenAI function name and calling `tool.arun()` with the declared arguments."""

    @inject
    def __init__(self, tools: list[StagedBaseTool]):
        self.__tools: dict[str, StagedBaseTool] = {
            tool.tool_config.open_ai_tool.function.name: tool for tool in tools
        }

    async def get_content(self, messages: list[Message]) -> str | None:
        tool_name = await self.get_tool_name()
        tool = self.__tools.get(tool_name)
        if tool is None:
            logger.warning(
                "StagedToolSyntheticInjector: tool '%s' not found in staged tools, skipping",
                tool_name,
            )
            return None
        arguments = await self.get_arguments()
        result = await tool.arun(_ARUN_SYNTHETIC_CALL_ID, **arguments)
        return result.content
