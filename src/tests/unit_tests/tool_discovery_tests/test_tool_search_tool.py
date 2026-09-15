from unittest.mock import MagicMock

from quickapp.config.tools.base import (
    OpenAiToolConfig,
    OpenAiToolFunction,
    OpenAiToolFunctionParameters,
)
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
