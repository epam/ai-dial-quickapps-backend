from injector import inject

from quickapp.common import StagedBaseTool
from quickapp.config.tools.base import BaseOpenAITool
from quickapp.config.toolsets.base import BaseToolSet
from quickapp.core.agent.models import OpenAiToolConfigDict
from quickapp.tool_discovery._tool_discovery_config import ToolDiscoveryConfig


@inject
class DeferredToolsContext:
    """Request-scoped holder for tool catalog and full definitions of deferred toolsets."""

    def __init__(self) -> None:
        self._catalog: list[dict[str, str]] = []
        self._definitions: dict[str, OpenAiToolConfigDict] = {}

    def register_staged_tools(self, tools: list[StagedBaseTool]) -> None:
        entries: list[tuple[BaseOpenAITool, str]] = [
            (t.tool_config, name)
            for t in tools
            if isinstance(t.tool_config, BaseOpenAITool)
            and (name := t.tool_config.open_ai_tool.function.name)
        ]
        self._catalog.extend(
            {
                "name": name,
                "description": tool_config.open_ai_tool.function.description or "",
            }
            for tool_config, name in entries
        )
        self._definitions.update(
            {
                name: tool_config.open_ai_tool.model_dump(mode="json", exclude_none=True)
                for tool_config, name in entries
            }
        )

    @property
    def deferred_names(self) -> frozenset[str]:
        return frozenset(self._definitions.keys())

    @property
    def catalog(self) -> list[dict[str, str]]:
        return list(self._catalog)

    def get_definition(self, name: str) -> OpenAiToolConfigDict | None:
        return self._definitions.get(name)


def is_toolset_deferred(
    toolset: BaseToolSet,
    discovery_cfg: ToolDiscoveryConfig | None,
    tool_count: int,
) -> bool:
    return (
        toolset.deferred is not False
        and discovery_cfg is not None
        and discovery_cfg.enabled
        and tool_count >= discovery_cfg.min_tools_for_deferral
    )
