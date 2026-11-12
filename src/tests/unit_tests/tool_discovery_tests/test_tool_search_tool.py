from unittest.mock import AsyncMock, MagicMock, call

import pytest

from quickapp.common.deferred_tool_types import (
    DeferredToolCatalogEntry,
    DeferredToolDefinition,
    DeferredToolsetSummary,
)
from quickapp.common.deployment_usage import DeploymentUsage, ModelUsage
from quickapp.config.tools.base import (
    OpenAiToolConfig,
    OpenAiToolFunction,
    OpenAiToolFunctionParameters,
)
from quickapp.tool_discovery._routing_result import RoutingResult
from quickapp.tool_discovery._tool_search_stage_wrapper import _ToolSearchStageWrapper
from quickapp.tool_discovery._tool_search_tool import _ToolSearchTool


def _make_open_ai_tool(description: str = "Search for additional tools.") -> OpenAiToolConfig:
    return OpenAiToolConfig(
        function=OpenAiToolFunction(
            name="internal_tool_search",
            description=description,
            parameters=OpenAiToolFunctionParameters(type="object", properties={}),
        )
    )


def _make_tool(
    *,
    routing: RoutingResult | None = None,
    toolset_summaries: list[DeferredToolsetSummary] | None = None,
    catalog: list[DeferredToolCatalogEntry] | None = None,
    definitions: list[DeferredToolDefinition] | None = None,
    lazy_holder: MagicMock | None = None,
) -> _ToolSearchTool:
    strategy = MagicMock()
    strategy.search = AsyncMock(return_value=routing or RoutingResult())
    return _ToolSearchTool(
        stage_wrapper_builder=MagicMock(),
        tool_config=MagicMock(),
        perf_timer=MagicMock(),
        catalog=catalog or [],
        definitions=definitions or [],
        toolset_summaries=toolset_summaries or [],
        lazy_holder=lazy_holder or MagicMock(),
        strategy=strategy,
    )


_CATALOG: list[DeferredToolCatalogEntry] = [
    {"name": "tool_a", "description": "Does A", "toolset": "ts"}
]


def _routed_tool(routed: list[str], lazy_holder: MagicMock | None = None) -> _ToolSearchTool:
    return _make_tool(
        routing=RoutingResult(names=routed),
        catalog=_CATALOG,
        definitions=[DeferredToolDefinition(name="tool_a", definition={"type": "function"})],
        lazy_holder=lazy_holder,
    )


class TestEnrichOpenAiToolSchema:
    def test_no_op_when_no_deferred_toolsets(self):
        tool = _make_tool()
        open_ai_tool = _make_open_ai_tool()

        result = tool.enrich_openai_tool_schema(open_ai_tool)

        assert result.function.description == "Search for additional tools."

    def test_appends_toolset_with_description_and_tool_count(self):
        tool = _make_tool(
            toolset_summaries=[
                {"name": "salesforce", "description": "Query Salesforce records", "tool_count": 12}
            ]
        )
        open_ai_tool = _make_open_ai_tool("Search for additional tools.")

        result = tool.enrich_openai_tool_schema(open_ai_tool)

        assert result.function.description == (
            "Search for additional tools.\n\n"
            "Additional toolsets available for discovery:\n"
            "- salesforce. Available tools: 12. Query Salesforce records"
        )

    def test_appends_toolset_name_and_count_only_when_description_is_none(self):
        tool = _make_tool(
            toolset_summaries=[{"name": "internal-utils", "description": None, "tool_count": 1}]
        )
        open_ai_tool = _make_open_ai_tool("Search for additional tools.")

        result = tool.enrich_openai_tool_schema(open_ai_tool)

        assert result.function.description == (
            "Search for additional tools.\n\n"
            "Additional toolsets available for discovery:\n"
            "- internal-utils. Available tools: 1."
        )

    def test_appends_multiple_toolsets_in_order(self):
        tool = _make_tool(
            toolset_summaries=[
                {"name": "toolset_a", "description": "Does A", "tool_count": 3},
                {"name": "toolset_b", "description": None, "tool_count": 7},
            ]
        )
        open_ai_tool = _make_open_ai_tool("Search for additional tools.")

        result = tool.enrich_openai_tool_schema(open_ai_tool)

        assert result.function.description == (
            "Search for additional tools.\n\n"
            "Additional toolsets available for discovery:\n"
            "- toolset_a. Available tools: 3. Does A\n"
            "- toolset_b. Available tools: 7."
        )


class TestRoutingUsage:
    @pytest.mark.asyncio
    async def test_result_carries_routing_call_usage(self):
        tool = _make_tool(
            routing=RoutingResult(
                usage=ModelUsage(model="router-model", prompt_tokens=120, completion_tokens=8)
            ),
            catalog=_CATALOG,
        )

        result = await tool._run_in_stage_async(None, query="find a tool")

        assert result.usage == [
            DeploymentUsage(
                model_name="router-model",
                deployment_name=tool._resolve_tool_name(),
                deployment_id="router-model",
                prompt_tokens=120,
                completion_tokens=8,
            )
        ]

    @pytest.mark.asyncio
    async def test_result_has_no_usage_when_routing_reports_none(self):
        tool = _make_tool(routing=RoutingResult(), catalog=_CATALOG)

        result = await tool._run_in_stage_async(None, query="find a tool")

        assert result.usage is None


class TestRunInStage:
    @pytest.mark.asyncio
    async def test_returns_matched_names_as_json_list(self):
        lazy_holder = MagicMock()
        tool = _routed_tool(["tool_a"], lazy_holder)

        result = await tool._run_in_stage_async(query="q")

        assert result.content == '["tool_a"]'
        assert result.content_type == "application/json"
        lazy_holder.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_skips_unknown_names(self):
        tool = _routed_tool(["ghost", "tool_a"])

        result = await tool._run_in_stage_async(query="q")

        assert result.content == '["tool_a"]'

    @pytest.mark.asyncio
    async def test_no_match_returns_text(self):
        lazy_holder = MagicMock()
        tool = _routed_tool(["ghost"], lazy_holder)

        result = await tool._run_in_stage_async(query="q")

        assert result.content == "No matching tools found for the given query."
        assert result.content_type == "text/plain"
        lazy_holder.add.assert_not_called()


class TestWarnings:
    @pytest.mark.asyncio
    async def test_routing_warnings_are_written_to_the_stage(self):
        warnings = ["Routing model 'm1' rejected the request: unsupported."]
        tool = _make_tool(routing=RoutingResult(warnings=warnings), catalog=_CATALOG)
        stage_wrapper = MagicMock(spec=_ToolSearchStageWrapper)

        await tool._run_in_stage_async(stage_wrapper, query="q")

        stage_wrapper.add_warnings.assert_called_once_with(warnings)

    def test_stage_wrapper_formats_each_warning(self):
        wrapper = _ToolSearchStageWrapper(stage=MagicMock())
        wrapper.append_stage_content = MagicMock()  # type: ignore[method-assign]

        wrapper.add_warnings(["first", "second"])

        assert wrapper.append_stage_content.call_args_list == [
            call("> ##### Warning:\nfirst\n"),
            call("> ##### Warning:\nsecond\n"),
        ]
