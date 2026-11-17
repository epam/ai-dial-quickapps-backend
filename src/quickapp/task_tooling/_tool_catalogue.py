from aidial_sdk.chat_completion.request import StaticTool
from injector import ProviderOf, inject

from quickapp.common import StagedBaseTool
from quickapp.common.tool_names import (
    INTERNAL_ATTACHMENTS_AVAILABLE_CONTEXT_TOOL_NAME,
    INTERNAL_ATTACHMENTS_GET_CONTENT_TOOL_NAME,
    INTERNAL_FILE_READ_LINES_TOOL_NAME,
    INTERNAL_FILE_SEARCH_TOOL_NAME,
    INTERNAL_MCP_READ_RESOURCE_TOOL_NAME,
    INTERNAL_RUN_TASK_TOOL_NAME,
    INTERNAL_SKILLS_READ_SKILL_TOOL_NAME,
    INTERNAL_TOOL_SEARCH_TOOL_NAME,
)

# Added to every explicit list: the task inherits skills, contexts and MCP resources,
# whose prompt parts are always rendered, and an offloaded tool result points at the
# file readers. The allowlist only narrows, so names the app lacks are harmless.
IMPLICIT_TASK_TOOL_NAMES: frozenset[str] = frozenset(
    {
        INTERNAL_SKILLS_READ_SKILL_TOOL_NAME,
        INTERNAL_ATTACHMENTS_AVAILABLE_CONTEXT_TOOL_NAME,
        INTERNAL_ATTACHMENTS_GET_CONTENT_TOOL_NAME,
        INTERNAL_MCP_READ_RESOURCE_TOOL_NAME,
        INTERNAL_FILE_READ_LINES_TOOL_NAME,
        INTERNAL_FILE_SEARCH_TOOL_NAME,
    }
)

# Never delegable by name: a task cannot run tasks, and an explicit list turns tool
# discovery off in the task.
_NON_DELEGABLE_TOOL_NAMES: frozenset[str] = frozenset(
    {INTERNAL_RUN_TASK_TOOL_NAME, INTERNAL_TOOL_SEARCH_TOOL_NAME}
)


@inject
class _DelegableToolNames:
    """Names of the delegating agent's tools that a task may be given.

    Resolved lazily at call time: the run_task tool is itself one of these tools, so
    resolving the list while it is built would cycle. Deferred tools are included
    (they live in ``list[StagedBaseTool]``); model-hidden and client tools are not.
    """

    def __init__(
        self,
        tools: ProviderOf[list[StagedBaseTool]],
        static_tools: ProviderOf[list[StaticTool]],
    ) -> None:
        self.__tools = tools
        self.__static_tools = static_tools

    def names(self) -> list[str]:
        names = {name for tool in self.__tools.get() if (name := tool.openai_function_name())}
        names |= {tool.static_function.name for tool in self.__static_tools.get()}
        return sorted(names - _NON_DELEGABLE_TOOL_NAMES)
