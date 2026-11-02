from unittest.mock import AsyncMock, MagicMock

import pytest

from quickapp.common.deployment_usage import DeploymentUsage, ModelUsage
from quickapp.config.tools.base import (
    OpenAiToolConfig,
    OpenAiToolFunction,
    OpenAiToolFunctionParameters,
)
from quickapp.tool_discovery._anonymous_agent import _RoutingResult
from quickapp.tool_discovery._tool_search_tool import _ToolSearchTool


def _make_open_ai_tool(description: str = "Search for additional tools.") -> OpenAiToolConfig:
    return OpenAiToolConfig(
        function=OpenAiToolFunction(
            name="internal_tool_search",
            description=description,
            parameters=OpenAiToolFunctionParameters(type="object", properties={}),
        )
    )


def _make_tool_search_tool(toolset_summaries: list[dict[str, str | int | None]]) -> _ToolSearchTool:
    return _ToolSearchTool(
        stage_wrapper_builder=MagicMock(),
        tool_config=MagicMock(),
        perf_timer=MagicMock(),
        catalog=[],
        definitions=[],
        toolset_summaries=toolset_summaries,
        lazy_holder=MagicMock(),
        anonymous_agent=MagicMock(),
    )


class TestEnrichOpenAiToolSchema:
    def test_no_op_when_no_deferred_toolsets(self):
        tool = _make_tool_search_tool([])
        open_ai_tool = _make_open_ai_tool()

        result = tool.enrich_openai_tool_schema(open_ai_tool)

        assert result.function.description == "Search for additional tools."

    def test_appends_toolset_with_description_and_tool_count(self):
        tool = _make_tool_search_tool(
            [{"name": "salesforce", "description": "Query Salesforce records", "tool_count": 12}]
        )
        open_ai_tool = _make_open_ai_tool("Search for additional tools.")

        result = tool.enrich_openai_tool_schema(open_ai_tool)

        assert result.function.description == (
            "Search for additional tools.\n\n"
            "Additional toolsets available for discovery:\n"
            "- salesforce. Available tools: 12. Query Salesforce records"
        )

    def test_appends_toolset_name_and_count_only_when_description_is_none(self):
        tool = _make_tool_search_tool(
            [{"name": "internal-utils", "description": None, "tool_count": 1}]
        )
        open_ai_tool = _make_open_ai_tool("Search for additional tools.")

        result = tool.enrich_openai_tool_schema(open_ai_tool)

        assert result.function.description == (
            "Search for additional tools.\n\n"
            "Additional toolsets available for discovery:\n"
            "- internal-utils. Available tools: 1."
        )

    def test_appends_multiple_toolsets_in_order(self):
        tool = _make_tool_search_tool(
            [
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
    @staticmethod
    def _make_tool(routing: _RoutingResult) -> _ToolSearchTool:
        anonymous_agent = MagicMock()
        anonymous_agent.route = AsyncMock(return_value=routing)
        return _ToolSearchTool(
            stage_wrapper_builder=MagicMock(),
            tool_config=MagicMock(),
            perf_timer=MagicMock(),
            catalog=[{"name": "tool_a", "description": "Does A"}],
            definitions=[],
            toolset_summaries=[],
            lazy_holder=MagicMock(),
            anonymous_agent=anonymous_agent,
        )

    @pytest.mark.asyncio
    async def test_result_carries_routing_call_usage(self):
        tool = self._make_tool(
            _RoutingResult(
                usage=ModelUsage(model="router-model", prompt_tokens=120, completion_tokens=8)
            )
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
        tool = self._make_tool(_RoutingResult())

        result = await tool._run_in_stage_async(None, query="find a tool")

        assert result.usage is None
