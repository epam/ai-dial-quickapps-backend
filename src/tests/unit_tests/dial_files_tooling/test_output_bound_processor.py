import pytest
from aidial_sdk.chat_completion import Attachment

from quickapp.common.abstract.tool_call_result_processor import ProcessingContext
from quickapp.common.tool_call_result import ToolCallResult
from quickapp.common.tool_names import INTERNAL_FILE_TOOL_NAME_PREFIX
from quickapp.common.utils import fenced_code_block
from quickapp.dial_files_tooling import dial_files_tooling_module  # noqa: F401  (loads all tools)
from quickapp.dial_files_tooling._base_file_tool import _DialFileTool
from quickapp.dial_files_tooling._output_bound_processor import (
    MAX_RESULT_CHARS,
    FileToolResultBoundProcessor,
)
from quickapp.dial_files_tooling._tool_configs import ALL_FILE_TOOL_CONFIGS

_FILE_TOOL_NAMES = [config.open_ai_tool.function.name for config in ALL_FILE_TOOL_CONFIGS]
_NOTICE_TAIL = "request a smaller range or a narrower query --"


def _ctx(tool_name: str) -> ProcessingContext:
    return ProcessingContext(tool_call_id="id1", tool_name=tool_name)


def _result(content: str, **kwargs) -> ToolCallResult:
    return ToolCallResult(tool_call_id="id1", content=content, content_type="text/plain", **kwargs)


def _lines(count: int, width: int = 100) -> str:
    return "\n".join(f"{i}:" + "a" * width for i in range(count))


class TestFileToolResultBoundProcessor:
    @pytest.mark.asyncio
    async def test_non_file_tool_is_never_touched(self):
        result = _result("x" * (MAX_RESULT_CHARS * 3))
        out = await FileToolResultBoundProcessor().process(result, _ctx("rest_get_logs"))
        assert out is result

    @pytest.mark.asyncio
    async def test_small_file_result_is_returned_as_is(self):
        result = _result("short")
        out = await FileToolResultBoundProcessor().process(result, _ctx("internal_file_list"))
        assert out is result

    @pytest.mark.asyncio
    async def test_result_at_limit_is_returned_as_is(self):
        result = _result("x" * MAX_RESULT_CHARS)
        out = await FileToolResultBoundProcessor().process(result, _ctx("internal_file_list"))
        assert out is result

    @pytest.mark.asyncio
    async def test_oversized_result_is_cut_on_line_boundary_with_notice(self):
        content = _lines(1000)
        out = await FileToolResultBoundProcessor().process(
            _result(content), _ctx("internal_file_list")
        )
        body, _, notice = out.content.rpartition("\n")
        assert notice == f"-- output truncated at {MAX_RESULT_CHARS} characters; {_NOTICE_TAIL}"
        assert len(body) <= MAX_RESULT_CHARS
        assert content.startswith(body)
        assert content[len(body)] == "\n"

    @pytest.mark.asyncio
    async def test_oversized_fenced_result_keeps_its_fence_closed(self):
        content = fenced_code_block(_lines(1000))
        out = await FileToolResultBoundProcessor().process(
            _result(content), _ctx("internal_file_find")
        )
        lines = out.content.splitlines()
        assert lines[0] == "```"
        assert lines[-2] == "```"
        assert lines.count("```") == 2

    @pytest.mark.asyncio
    async def test_longer_opening_fence_is_closed_with_the_same_length(self):
        content = fenced_code_block("```nested```\n" + _lines(1000))
        out = await FileToolResultBoundProcessor().process(
            _result(content), _ctx("internal_file_find")
        )
        lines = out.content.splitlines()
        assert lines[0] == "````"
        assert lines[-2] == "````"

    @pytest.mark.asyncio
    async def test_other_result_fields_are_preserved(self):
        attachment = Attachment(title="a", url="files/b/a.txt", type="text/plain")
        result = _result(_lines(1000), attachments=[attachment], state={"k": "v"})
        out = await FileToolResultBoundProcessor().process(result, _ctx("internal_file_list"))
        assert out.tool_call_id == "id1"
        assert out.attachments == [attachment]
        assert out.state == {"k": "v"}
        assert result.content == _lines(1000)

    def test_runs_after_offload(self):
        # Offload (order 0) must shrink or exclude first; the bound then backstops the rest.
        assert FileToolResultBoundProcessor.order > 0


class TestEveryFileToolIsCovered:
    """Adding a file tool must not be able to skip output bounding."""

    def test_every_file_tool_class_is_registered_in_all_file_tool_configs(self):
        # A new `_DialFileTool` subclass without a config entry would bypass this check
        # and the module's tool list alike -- fail loudly so it gets registered.
        assert len(_DialFileTool.__subclasses__()) == len(ALL_FILE_TOOL_CONFIGS)

    @pytest.mark.parametrize("tool_name", _FILE_TOOL_NAMES)
    def test_tool_name_carries_the_prefix_the_processor_matches_on(self, tool_name: str):
        assert tool_name.startswith(INTERNAL_FILE_TOOL_NAME_PREFIX)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("tool_name", _FILE_TOOL_NAMES)
    async def test_huge_result_of_any_file_tool_is_bounded(self, tool_name: str):
        out = await FileToolResultBoundProcessor().process(
            _result("x" * (MAX_RESULT_CHARS * 5)), _ctx(tool_name)
        )
        assert len(out.content) < MAX_RESULT_CHARS + 200
        assert out.content.endswith(_NOTICE_TAIL)
