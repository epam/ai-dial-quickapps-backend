from quickapp.common.deferred_tool_types import DeferredToolCatalogEntry
from quickapp.common.localized_string import resolve_localized
from quickapp.common.staged_base_tool import StagedBaseTool
from quickapp.config.tool_discovery import ToolDiscoveryConfig
from quickapp.config.tools.base import (
    BaseOpenAITool,
    OpenAiToolConfigDict,
    remove_const_schema_params,
)
from quickapp.config.toolsets.base import BaseToolSet


class DeferredToolsAccumulator:
    """Base contract for a tooling module's own deferred-tool registry.

    Concrete subclasses are bound request-scoped by their owning module (mirrors
    `ToolingContextBase`), not by a Module of their own.
    """

    def __init__(self) -> None:
        self._catalog: list[DeferredToolCatalogEntry] = []
        self._definitions: dict[str, OpenAiToolConfigDict] = {}
        self._toolset_summaries: list[dict[str, str | int | None]] = []
        self._registered: set[tuple[str, tuple[str, ...]]] = set()

    def register_deferred_tools(self, toolset: BaseToolSet, tools: list[StagedBaseTool]) -> None:
        entries: list[tuple[StagedBaseTool, BaseOpenAITool, str]] = [
            (t, t.tool_config, name)
            for t in tools
            if isinstance(t.tool_config, BaseOpenAITool)
            and (name := t.tool_config.open_ai_tool.function.name)
        ]
        toolset_name = resolve_localized(toolset.name)
        # Providers that call this are unscoped and re-run several times per request, so
        # registration must be idempotent. Toolset names may collide, so the key also
        # includes the tool names.
        registration_key = (
            toolset_name,
            tuple(sorted(name for _, _, name in entries)),
        )
        if registration_key in self._registered:
            return
        self._registered.add(registration_key)
        self._catalog.extend(
            {
                "name": name,
                "description": tool_config.open_ai_tool.function.description or "",
                "toolset": toolset_name,
            }
            for _, tool_config, name in entries
        )
        self._definitions.update(
            {
                # Apply the same transform pipeline as the eager path (AgentModule.provide_openai_tools)
                # so a discovered tool's schema matches what it would have looked like loaded eagerly.
                name: tool.enrich_openai_tool_schema(
                    remove_const_schema_params(tool_config.open_ai_tool)
                ).model_dump(mode="json", exclude_none=True)
                for tool, tool_config, name in entries
            }
        )
        self._toolset_summaries.append(
            {
                "name": toolset_name,
                "description": (
                    resolve_localized(toolset.description) if toolset.description else None
                ),
                "tool_count": len(entries),
            }
        )

    @property
    def deferred_names(self) -> frozenset[str]:
        return frozenset(self._definitions.keys())

    # Sorted: toolsets may register in parallel, in completion order.
    @property
    def catalog(self) -> list[DeferredToolCatalogEntry]:
        return sorted(self._catalog, key=lambda e: e["name"])

    @property
    def toolset_summaries(self) -> list[dict[str, str | int | None]]:
        return sorted(self._toolset_summaries, key=lambda e: str(e["name"]))

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
