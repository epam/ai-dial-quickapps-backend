from unittest.mock import AsyncMock, MagicMock

import pytest

from quickapp.common.abstract.tool_call_result_processor import (
    ProcessingContext,
    ToolCallResultProcessor,
)
from quickapp.common.staged_base_tool import StagedBaseTool
from quickapp.common.tool_call_result import ToolCallResult
from quickapp.core.agent.tool_executor import ToolExecutor


def _make_tool_call(name: str, tc_id: str = "id1", arguments: str = "{}") -> MagicMock:
    tc = MagicMock()
    tc.name = name
    tc.id = tc_id
    tc.arguments = arguments
    return tc


def _make_tool(name: str, result: ToolCallResult) -> MagicMock:
    tool = MagicMock()
    tool_config = MagicMock()
    open_ai_tool = MagicMock()
    function = MagicMock()
    function.name = name
    open_ai_tool.function = function
    tool_config.open_ai_tool = open_ai_tool
    tool._tool_config = tool_config
    tool.openai_function_name = MagicMock(return_value=name)
    tool.build_argument_stream_presentation = MagicMock(return_value=None)

    async def _arun(*, tool_call_id, **_kwargs):
        result.tool_call_id = tool_call_id
        return result

    tool.arun = AsyncMock(side_effect=_arun)
    return tool


class _DoubleProcessor(ToolCallResultProcessor):
    order = 50

    async def process(self, result: ToolCallResult, ctx: ProcessingContext) -> ToolCallResult:
        return ToolCallResult(
            tool_call_id=result.tool_call_id,
            content=result.content + result.content,
            content_type=result.content_type,
        )


class _AppendProcessor(ToolCallResultProcessor):
    order = 100

    def __init__(self, suffix: str) -> None:
        self._suffix = suffix

    async def process(self, result: ToolCallResult, ctx: ProcessingContext) -> ToolCallResult:
        return ToolCallResult(
            tool_call_id=result.tool_call_id,
            content=result.content + self._suffix,
            content_type=result.content_type,
        )


class TestToolExecutorProcessors:
    @pytest.mark.asyncio
    async def test_processors_are_applied_after_enrichers(self):
        base_result = ToolCallResult(content="hello", content_type="text/plain")
        tool = _make_tool("my_tool", base_result)
        executor = ToolExecutor(
            tools=[tool],
            model_hidden_tools=[],
            enrichers=[],
            perf_timer=MagicMock(),
            processors=[_AppendProcessor("!")],
        )

        results = await executor.execute([_make_tool_call("my_tool")])

        assert len(results) == 1
        assert results[0].content == "hello!"

    @pytest.mark.asyncio
    async def test_processors_run_in_order(self):
        # _DoubleProcessor (order=50) runs before _AppendProcessor (order=100)
        # "hi" → double → "hihi" → append "!" → "hihi!"
        base_result = ToolCallResult(content="hi", content_type="text/plain")
        tool = _make_tool("my_tool", base_result)
        executor = ToolExecutor(
            tools=[tool],
            model_hidden_tools=[],
            enrichers=[],
            perf_timer=MagicMock(),
            processors=[_AppendProcessor("!"), _DoubleProcessor()],
        )

        results = await executor.execute([_make_tool_call("my_tool")])

        assert results[0].content == "hihi!"

    @pytest.mark.asyncio
    async def test_empty_processors_returns_original(self):
        base_result = ToolCallResult(content="original", content_type="text/plain")
        tool = _make_tool("my_tool", base_result)
        executor = ToolExecutor(
            tools=[tool],
            model_hidden_tools=[],
            enrichers=[],
            perf_timer=MagicMock(),
            processors=[],
        )

        results = await executor.execute([_make_tool_call("my_tool")])

        assert results[0].content == "original"

    @pytest.mark.asyncio
    async def test_ctx_carries_tool_name_and_id(self):
        captured: list[ProcessingContext] = []

        class _CaptureProcessor(ToolCallResultProcessor):
            async def process(
                self, result: ToolCallResult, ctx: ProcessingContext
            ) -> ToolCallResult:
                captured.append(ctx)
                return result

        base_result = ToolCallResult(content="x", content_type="text/plain")
        tool = _make_tool("specific_tool", base_result)
        executor = ToolExecutor(
            tools=[tool],
            model_hidden_tools=[],
            enrichers=[],
            perf_timer=MagicMock(),
            processors=[_CaptureProcessor()],
        )

        await executor.execute([_make_tool_call("specific_tool", tc_id="call_abc")])

        assert captured[0].tool_name == "specific_tool"
        assert captured[0].tool_call_id == "call_abc"

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_synthetic_error_result(self):
        executor = ToolExecutor(
            tools=[],
            model_hidden_tools=[],
            enrichers=[],
            perf_timer=MagicMock(),
            processors=[],
        )

        results = await executor.execute(
            [_make_tool_call("missing_tool", tc_id="u1")],
        )

        assert len(results) == 1
        assert results[0].tool_call_id == "u1"
        assert "missing_tool" in results[0].content
        assert "Unknown tool" in results[0].content
        assert results[0].content_type == "text/markdown"

    @pytest.mark.asyncio
    async def test_unknown_tool_alongside_known_tool_still_executes_known_tool(self):
        known = _make_tool("known_tool", ToolCallResult(content="ok", content_type="text/plain"))
        executor = ToolExecutor(
            tools=[known],
            model_hidden_tools=[],
            enrichers=[],
            perf_timer=MagicMock(),
            processors=[],
        )

        results = await executor.execute(
            [
                _make_tool_call("missing_tool", tc_id="u1"),
                _make_tool_call("known_tool", tc_id="k1"),
            ]
        )

        known.arun.assert_awaited_once()
        assert len(results) == 2
        assert results[0].tool_call_id == "u1"
        assert "missing_tool" in results[0].content
        assert results[1].tool_call_id == "k1"
        assert results[1].content == "ok"

    @pytest.mark.asyncio
    async def test_unknown_tool_reply_lists_available_tools(self):
        tools = [
            _make_tool(name, ToolCallResult(content="ok", content_type="text/plain"))
            for name in ("My_MCP_validate_sql", "My_MCP_describe_entity")
        ]
        executor = ToolExecutor(
            tools=tools,
            model_hidden_tools=[],
            enrichers=[],
            perf_timer=MagicMock(),
            processors=[],
        )

        results = await executor.execute([_make_tool_call("validate_sql")])

        assert results[0].content == (
            "The tool call failed with an error: Unknown tool 'validate_sql'.\n\n"
            "This tool does not exist. Use one of the available tools: "
            "`My_MCP_describe_entity`, `My_MCP_validate_sql`."
        )


class TestToolExecutorModelHiddenTools:
    @staticmethod
    def _executor(tools: list, hidden: list) -> ToolExecutor:
        return ToolExecutor(
            tools=tools,
            model_hidden_tools=hidden,
            enrichers=[],
            perf_timer=MagicMock(),
            processors=[],
        )

    @pytest.mark.asyncio
    async def test_model_hidden_call_gets_reserved_reply_and_tool_does_not_run(self):
        hidden = _make_tool(
            "prime_memories", ToolCallResult(content="x", content_type="text/plain")
        )
        executor = self._executor([], [hidden])

        results = await executor.execute([_make_tool_call("prime_memories", tc_id="call-1")])

        hidden.arun.assert_not_called()
        assert results[0].tool_call_id == "call-1"
        assert "not available to you" in results[0].content
        assert "do not call it" in results[0].content
        assert "check the tool name" not in results[0].content.lower()

    @pytest.mark.asyncio
    async def test_unknown_name_keeps_unknown_tool_reply(self):
        hidden = _make_tool("hidden", ToolCallResult(content="x", content_type="text/plain"))
        executor = self._executor([], [hidden])

        results = await executor.execute([_make_tool_call("nope")])

        assert "does not exist" in results[0].content

    @pytest.mark.asyncio
    async def test_unknown_tool_reply_does_not_list_hidden_tools(self):
        visible = _make_tool("search", ToolCallResult(content="found", content_type="text/plain"))
        hidden = _make_tool("save", ToolCallResult(content="x", content_type="text/plain"))
        executor = self._executor([visible], [hidden])

        results = await executor.execute([_make_tool_call("nope")])

        assert results[0].content == (
            "The tool call failed with an error: Unknown tool 'nope'.\n\n"
            "This tool does not exist. Use one of the available tools: `search`."
        )

    @pytest.mark.asyncio
    async def test_visible_tool_still_runs_next_to_hidden_one(self):
        visible = _make_tool("search", ToolCallResult(content="found", content_type="text/plain"))
        hidden = _make_tool("save", ToolCallResult(content="x", content_type="text/plain"))
        executor = self._executor([visible], [hidden])

        results = await executor.execute(
            [_make_tool_call("search", tc_id="a"), _make_tool_call("save", tc_id="b")]
        )

        visible.arun.assert_awaited_once()
        hidden.arun.assert_not_called()
        assert results[0].content == "found"
        assert "not available to you" in results[1].content


class TestToolExecutorResolveToolName:
    @staticmethod
    def _tools(names: dict[str, str | None]) -> list[StagedBaseTool]:
        tools = []
        for name, unprefixed in names.items():
            tool = _make_tool(name, ToolCallResult(content="x", content_type="text/plain"))
            tool.unprefixed_name = unprefixed
            tools.append(tool)
        return tools

    def _executor(
        self, names: dict[str, str | None], hidden: dict[str, str | None] | None = None
    ) -> ToolExecutor:
        return ToolExecutor(
            tools=self._tools(names),
            model_hidden_tools=self._tools(hidden or {}),
            enrichers=[],
            perf_timer=MagicMock(),
            processors=[],
        )

    def test_missing_prefix_resolves(self):
        executor = self._executor(
            {
                "My_MCP_validate_sql": "validate_sql",
                "My_MCP_describe_entity": "describe_entity",
            }
        )

        assert executor.resolve_tool_name("validate_sql") == "My_MCP_validate_sql"

    def test_same_tool_in_two_toolsets_is_not_resolved(self):
        executor = self._executor({"A_search": "search", "B_search": "search"})

        assert executor.resolve_tool_name("search") is None

    def test_exact_name_is_not_resolved(self):
        executor = self._executor({"search": None, "A_search": "search"})

        assert executor.resolve_tool_name("search") is None

    def test_model_hidden_tool_is_not_a_candidate(self):
        executor = self._executor({"search": None}, hidden={"My_MCP_save": "save"})

        assert executor.resolve_tool_name("save") is None

    def test_exact_model_hidden_name_is_not_resolved(self):
        executor = self._executor({"My_MCP_save": "save"}, hidden={"save": None})

        assert executor.resolve_tool_name("save") is None

    def test_unmatched_name_is_not_resolved(self):
        executor = self._executor({"My_MCP_validate_sql": "validate_sql"})

        assert executor.resolve_tool_name("describe_entity") is None

    def test_part_of_the_tool_name_is_not_resolved(self):
        executor = self._executor({"My_MCP_validate_sql": "validate_sql"})

        assert executor.resolve_tool_name("sql") is None

    def test_partly_dropped_prefix_is_not_resolved(self):
        executor = self._executor({"My_MCP_validate_sql": "validate_sql"})

        assert executor.resolve_tool_name("MCP_validate_sql") is None

    def test_tool_without_unprefixed_name_is_never_resolved(self):
        executor = self._executor({"internal_skills_read_skill": None})

        assert executor.resolve_tool_name("read_skill") is None
