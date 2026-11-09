from aidial_sdk.chat_completion.request import StaticTool
from pydantic import BaseModel, ConfigDict

from quickapp.common.staged_base_tool import StagedBaseTool


class ToolAllowlist(BaseModel):
    """The tools one completion run may offer to and execute for its LLM.

    ``names=None`` allows every tool (a user request). A delegated task narrows its
    run to the names the delegating agent picked.
    """

    model_config = ConfigDict(frozen=True)

    names: frozenset[str] | None = None

    def allows(self, name: str | None) -> bool:
        return self.names is None or (name is not None and name in self.names)

    def filter_tools(self, tools: list[StagedBaseTool]) -> list[StagedBaseTool]:
        if self.names is None:
            return tools
        return [tool for tool in tools if self.allows(tool.openai_function_name())]

    def filter_static(self, tools: list[StaticTool]) -> list[StaticTool]:
        if self.names is None:
            return tools
        return [tool for tool in tools if self.allows(tool.static_function.name)]
