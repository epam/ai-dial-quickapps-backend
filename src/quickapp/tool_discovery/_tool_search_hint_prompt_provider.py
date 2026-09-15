from injector import inject

from quickapp.common.abstract.base_prompt_provider import PromptPartProvider
from quickapp.common.deferred_tool_types import DeferredToolsetSummary
from quickapp.common.tool_names import INTERNAL_TOOL_SEARCH_TOOL_NAME
from quickapp.tool_discovery._toolset_summary_format import format_toolset_summaries

_TOOL_SEARCH_HINT = (
    "If a user request might involve capabilities beyond your current listed tools, you are "
    "REQUIRED to:\n"
    f"1) Call `{INTERNAL_TOOL_SEARCH_TOOL_NAME}` with a brief description of the needed capability.\n"
    "2) Inspect any returned tools."
)


@inject
class _ToolSearchHintPromptProvider(PromptPartProvider):
    """Reminds the orchestrator to try tool discovery before declaring a limitation, and lists
    the toolsets currently withheld from the initial payload (name, tool count, description).
    """

    def __init__(self, toolset_summaries: list[DeferredToolsetSummary]) -> None:
        self.__toolset_summaries = toolset_summaries

    async def get_prompt_part(self) -> str:
        summaries = self.__toolset_summaries
        if not summaries:
            return _TOOL_SEARCH_HINT

        return (
            _TOOL_SEARCH_HINT
            + "\n\nAdditional toolsets available for discovery:\n"
            + format_toolset_summaries(summaries)
        )
