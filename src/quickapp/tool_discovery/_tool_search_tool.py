import json
import logging
from typing import Any

from injector import AssistedBuilder, inject

from quickapp.common import StagedBaseTool, ToolCallResult
from quickapp.common.abstract.base_tool_argument_transformer import ToolArgumentTransformer
from quickapp.common.base_stage_wrapper import BaseStageWrapper
from quickapp.common.deferred_tool_types import (
    DeferredToolCatalogEntry,
    DeferredToolDefinition,
    DeferredToolsetSummary,
)
from quickapp.common.perf_timer.perf_timer import PerformanceTimer
from quickapp.config.application import StageDisplayLevel
from quickapp.config.tools.base import OpenAiToolConfig, OpenAiToolConfigDict
from quickapp.config.tools.internal import InternalTool
from quickapp.core.agent.lazy_loaded_tools_holder import LazyLoadedToolsHolder
from quickapp.tool_discovery._anonymous_agent import _AnonymousAgent
from quickapp.tool_discovery._tool_search_stage_wrapper import _ToolSearchStageWrapper
from quickapp.tool_discovery._toolset_summary_format import format_toolset_summaries

logger = logging.getLogger(__name__)


@inject
class _ToolSearchTool(StagedBaseTool):
    """Meta-tool that discovers deferred tools on demand via an anonymous LLM routing call."""

    def __init__(
        self,
        stage_wrapper_builder: AssistedBuilder[_ToolSearchStageWrapper],
        tool_config: InternalTool,
        perf_timer: PerformanceTimer,
        catalog: list[DeferredToolCatalogEntry],
        definitions: list[DeferredToolDefinition],
        toolset_summaries: list[DeferredToolsetSummary],
        lazy_holder: LazyLoadedToolsHolder,
        anonymous_agent: _AnonymousAgent,
        stage_display_level: StageDisplayLevel = StageDisplayLevel.INFO,
        argument_transformers: list[ToolArgumentTransformer] | None = None,
        **kwargs: Any,
    ):
        super().__init__(
            stage_wrapper_builder=stage_wrapper_builder,  # type: ignore[arg-type]
            tool_config=tool_config,
            perf_timer=perf_timer,
            stage_display_level=stage_display_level,
            argument_transformers=argument_transformers,
            **kwargs,
        )
        self.__catalog = catalog
        self.__toolset_summaries = toolset_summaries
        self.__definitions_by_name: dict[str, OpenAiToolConfigDict] = {
            definition.name: definition.definition for definition in definitions
        }
        self.__lazy_holder = lazy_holder
        self.__anonymous_agent = anonymous_agent

    def enrich_openai_tool_schema(self, open_ai_tool: OpenAiToolConfig) -> OpenAiToolConfig:
        summaries = self.__toolset_summaries
        if not summaries:
            return open_ai_tool

        open_ai_tool.function.description = (
            open_ai_tool.function.description
            + "\n\nAdditional toolsets available for discovery:\n"
            + format_toolset_summaries(summaries)
        )
        return open_ai_tool

    async def _run_in_stage_async(
        self,
        stage_wrapper: BaseStageWrapper | None = None,
        tool_call_id: str | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> ToolCallResult:
        query: str = kwargs.get("query", "")
        catalog = self.__catalog

        if not catalog:
            result = ToolCallResult(
                content="No additional tools are available for discovery.",
                content_type="text/plain",
            )
            if stage_wrapper:
                stage_wrapper.add_result(result)
            return result

        matched_names = await self.__anonymous_agent.route(query, catalog)

        discovered: list[dict[str, str]] = []
        new_definitions = []
        for name in matched_names:
            definition = self.__definitions_by_name.get(name)
            if definition is None:
                logger.warning("tool_search matched unknown tool name %r — skipping", name)
                continue
            description: str = definition.get("function", {}).get("description", "")
            discovered.append({"name": name, "description": description})
            new_definitions.append(definition)

        if new_definitions:
            self.__lazy_holder.add(new_definitions)

        if discovered:
            content = json.dumps(discovered, ensure_ascii=False)
            content_type = "application/json"
        else:
            content = "No matching tools found for the given query."
            content_type = "text/plain"

        result = ToolCallResult(content=content, content_type=content_type)
        if stage_wrapper:
            stage_wrapper.add_result(result)
        return result
