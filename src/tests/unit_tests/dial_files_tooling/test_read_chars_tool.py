import pytest
from aidial_client._exception import ResourceNotFoundError

from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.config.dial_files import ToolCallResultOffloadSettings
from quickapp.dial_files_tooling._read_chars_tool import _ReadCharsTool
from quickapp.dial_files_tooling._tool_configs import READ_CHARS_TOOL_CONFIG
from quickapp.dial_files_tooling._utils import MAX_OUTPUT_CHARS
from tests.unit_tests.dial_files_tooling._helpers import make_service, make_tool


def _make_tool(content: str = "0123456789") -> _ReadCharsTool:
    service = make_service()
    service.download_file.return_value = (content.encode("utf-8"), None)
    return make_tool(_ReadCharsTool, READ_CHARS_TOOL_CONFIG, service=service)


async def _read(tool: _ReadCharsTool, offset: int, length: int, path: str = "f.txt") -> str:
    result = await tool._run_in_stage_async(
        stage_wrapper=None, path=path, offset=offset, length=length
    )
    return result.content


class TestReadChars:
    @pytest.mark.asyncio
    async def test_returns_slice_with_paging_footer(self):
        content = await _read(_make_tool(), offset=2, length=3)
        assert content.startswith("234\n")
        assert "chars 2-5 of 10" in content
        assert "next offset: 5" in content

    @pytest.mark.asyncio
    async def test_last_page_reports_end_of_file(self):
        content = await _read(_make_tool(), offset=8, length=5)
        assert content.startswith("89\n")
        assert "chars 8-10 of 10" in content
        assert "end of file" in content
        assert "next offset" not in content

    @pytest.mark.asyncio
    async def test_offset_at_eof_returns_empty_slice_and_end_marker(self):
        content = await _read(_make_tool(), offset=10, length=5)
        assert "chars 10-10 of 10" in content
        assert "end of file" in content

    @pytest.mark.asyncio
    async def test_empty_file_is_readable_from_zero(self):
        content = await _read(_make_tool(""), offset=0, length=5)
        assert "chars 0-0 of 0" in content
        assert "end of file" in content

    @pytest.mark.asyncio
    async def test_offset_beyond_eof_raises(self):
        with pytest.raises(InvalidToolCallParameterException) as exc:
            await _read(_make_tool(), offset=11, length=5)
        assert exc.value.parameter_name == "offset"
        assert "10" in exc.value.message

    @pytest.mark.asyncio
    async def test_negative_offset_raises(self):
        with pytest.raises(InvalidToolCallParameterException) as exc:
            await _read(_make_tool(), offset=-1, length=5)
        assert exc.value.parameter_name == "offset"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("length", [0, -3])
    async def test_non_positive_length_raises(self, length: int):
        with pytest.raises(InvalidToolCallParameterException) as exc:
            await _read(_make_tool(), offset=0, length=length)
        assert exc.value.parameter_name == "length"

    @pytest.mark.asyncio
    async def test_length_is_clamped_to_cap(self):
        tool = _make_tool("x" * (MAX_OUTPUT_CHARS * 3))
        content = await _read(tool, offset=0, length=10_000_000)
        body, _, footer = content.rpartition("\n")
        assert body == "x" * MAX_OUTPUT_CHARS
        assert f"next offset: {MAX_OUTPUT_CHARS}" in footer
        assert f"limited to {MAX_OUTPUT_CHARS}" in footer

    @pytest.mark.asyncio
    async def test_unclamped_read_has_no_limit_note(self):
        content = await _read(_make_tool(), offset=0, length=4)
        assert "limited" not in content

    @pytest.mark.asyncio
    async def test_offset_and_length_count_characters_not_bytes(self):
        content = await _read(_make_tool("héllo wörld ✓"), offset=6, length=5)
        assert content.startswith("wörld\n")
        assert "chars 6-11 of 13" in content

    @pytest.mark.asyncio
    async def test_pages_through_single_huge_line_without_loss_or_oversize(self):
        # Mirrors the failing case: a multi-megabyte file with very few lines.
        line = "".join(chr(ord("a") + i % 26) for i in range(400_000))
        text = "\n".join([line] * 20)
        tool = _make_tool(text)

        pieces: list[str] = []
        offset = 0
        while True:
            content = await _read(tool, offset=offset, length=MAX_OUTPUT_CHARS)
            body, _, footer = content.rpartition("\n")
            assert len(content.encode("utf-8")) < ToolCallResultOffloadSettings().size_threshold
            pieces.append(body)
            if "end of file" in footer:
                break
            offset += len(body)

        assert "".join(pieces) == text

    @pytest.mark.asyncio
    async def test_cap_stays_below_offload_threshold_in_worst_case_encoding(self):
        # 4 bytes per character is the UTF-8 worst case; the cap must fit with room
        # for the paging footer, since read-back results are never re-offloaded.
        worst_case_bytes = (MAX_OUTPUT_CHARS + 500) * 4
        default_threshold = ToolCallResultOffloadSettings.model_fields["size_threshold"].default
        assert worst_case_bytes < default_threshold

    @pytest.mark.asyncio
    async def test_relative_path_resolves_under_home(self):
        tool = _make_tool()
        await _read(tool, offset=0, length=2, path="reports/x.md")
        tool._dial_file_service.download_file.assert_awaited_once_with(
            "files/appbucket/reports/x.md"
        )

    @pytest.mark.asyncio
    async def test_missing_file_raises_friendly_not_found(self):
        tool = _make_tool()
        tool._dial_file_service.download_file.side_effect = ResourceNotFoundError(message="404")
        with pytest.raises(InvalidToolCallParameterException) as exc:
            await _read(tool, offset=0, length=2, path="missing.txt")
        assert exc.value.parameter_name == "path"
        assert "file not found" in exc.value.message
