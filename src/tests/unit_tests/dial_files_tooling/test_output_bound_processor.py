import pytest
from aidial_sdk.chat_completion import Attachment

from quickapp.common.abstract.tool_call_result_processor import ProcessingContext
from quickapp.common.tool_call_result import ToolCallResult
from quickapp.dial_files_tooling._offload_config import ResolvedOffloadConfig
from quickapp.dial_files_tooling._output_bound_processor import (
    MAX_RESULT_CHARS,
    ToolCallResultSizeLimitProcessor,
)

_TOOL_NAMES = [
    "internal_file_list",
    "internal_file_find",
    "rest_get_logs",
    "mcp_ms365_download",
    "my_deployment",
    "internal_python_interpreter",
]


def _processor(enabled: bool = False, size_threshold: int = 0) -> ToolCallResultSizeLimitProcessor:
    return ToolCallResultSizeLimitProcessor(
        ResolvedOffloadConfig(
            enabled=enabled, size_threshold=size_threshold, excluded_tools=frozenset()
        )
    )


def _ctx(tool_name: str) -> ProcessingContext:
    return ProcessingContext(tool_call_id="id1", tool_name=tool_name)


def _result(content: str, **kwargs) -> ToolCallResult:
    return ToolCallResult(tool_call_id="id1", content=content, content_type="text/plain", **kwargs)


class TestToolCallResultSizeLimitProcessor:
    @pytest.mark.asyncio
    async def test_small_result_is_returned_as_is(self):
        result = _result("short")
        out = await _processor().process(result, _ctx("rest_get_logs"))
        assert out is result

    @pytest.mark.asyncio
    async def test_result_at_limit_is_returned_as_is(self):
        result = _result("x" * MAX_RESULT_CHARS)
        out = await _processor().process(result, _ctx("rest_get_logs"))
        assert out is result

    @pytest.mark.asyncio
    async def test_oversized_result_is_replaced_by_an_error(self):
        out = await _processor().process(
            _result("x" * (MAX_RESULT_CHARS + 1)), _ctx("rest_get_logs")
        )
        assert out.content.startswith("Error:")
        assert "'rest_get_logs' completed" in out.content
        assert "too large" in out.content
        assert str(MAX_RESULT_CHARS + 1) in out.content
        assert f"the limit is {MAX_RESULT_CHARS}" in out.content

    @pytest.mark.asyncio
    async def test_oversized_content_is_not_leaked_into_the_error(self):
        out = await _processor().process(
            _result("secret " * MAX_RESULT_CHARS), _ctx("rest_get_logs")
        )
        assert "secret" not in out.content
        assert len(out.content) < 500

    @pytest.mark.asyncio
    async def test_other_result_fields_are_preserved(self):
        attachment = Attachment(title="a", url="files/b/a.txt", type="text/plain")
        content = "x" * (MAX_RESULT_CHARS + 1)
        result = _result(content, attachments=[attachment], state={"k": "v"})
        out = await _processor().process(result, _ctx("rest_get_logs"))
        assert out.tool_call_id == "id1"
        assert out.content_type == "text/plain"
        assert out.attachments == [attachment]
        assert out.state == {"k": "v"}
        assert result.content == content

    @pytest.mark.asyncio
    @pytest.mark.parametrize("tool_name", _TOOL_NAMES)
    async def test_huge_result_of_any_tool_is_replaced_by_an_error(self, tool_name: str):
        out = await _processor().process(_result("x" * (MAX_RESULT_CHARS * 5)), _ctx(tool_name))
        assert out.content.startswith("Error:")
        assert f"'{tool_name}'" in out.content

    @pytest.mark.asyncio
    async def test_limit_follows_a_raised_offload_threshold(self):
        threshold = MAX_RESULT_CHARS * 3
        result = _result("x" * threshold)
        out = await _processor(enabled=True, size_threshold=threshold).process(
            result, _ctx("rest_get_logs")
        )
        assert out is result

    @pytest.mark.asyncio
    async def test_error_reports_the_effective_limit(self):
        threshold = MAX_RESULT_CHARS * 3
        out = await _processor(enabled=True, size_threshold=threshold).process(
            _result("x" * (threshold + 1)), _ctx("rest_get_logs")
        )
        assert f"the limit is {threshold}" in out.content

    @pytest.mark.asyncio
    async def test_small_offload_threshold_does_not_lower_the_limit(self):
        result = _result("x" * MAX_RESULT_CHARS)
        out = await _processor(enabled=True, size_threshold=1_000).process(
            result, _ctx("rest_get_logs")
        )
        assert out is result

    @pytest.mark.asyncio
    async def test_threshold_is_ignored_when_offload_is_disabled(self):
        out = await _processor(enabled=False, size_threshold=MAX_RESULT_CHARS * 3).process(
            _result("x" * (MAX_RESULT_CHARS + 1)), _ctx("rest_get_logs")
        )
        assert out.content.startswith("Error:")

    def test_runs_after_offload(self):
        # Offload (order 0) must shrink or exclude first; the limit then backstops the rest.
        assert ToolCallResultSizeLimitProcessor.order > 0
