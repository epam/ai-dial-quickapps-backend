from unittest.mock import MagicMock

import pytest
from aidial_client._exception import ResourceNotFoundError

from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.dial_core_services.dial_file_service import FolderEntry
from quickapp.dial_files_tooling._search_in_file_tool import _SearchInFileTool
from quickapp.dial_files_tooling._tool_configs import SEARCH_IN_FILE_TOOL_CONFIG
from quickapp.dial_files_tooling._utils import code_block
from tests.unit_tests.dial_files_tooling._helpers import make_config, make_service, make_tool


def _make_tool(content: str) -> _SearchInFileTool:
    service = make_service()
    service.download_file.return_value = (content.encode("utf-8"), None)
    return _build(service)


def _build(service: MagicMock, max_files_scanned: int = 200) -> _SearchInFileTool:
    return make_tool(
        _SearchInFileTool,
        SEARCH_IN_FILE_TOOL_CONFIG,
        service=service,
        config=make_config(max_files_scanned=max_files_scanned),
    )


def _file(url: str, size: int = 10) -> FolderEntry:
    return FolderEntry(url=url, is_folder=False, size=size)


def _folder(url: str) -> FolderEntry:
    return FolderEntry(url=url, is_folder=True, size=None)


def _make_folder_tool(
    entries: list[FolderEntry],
    contents: dict[str, bytes],
    list_side_effect: Exception | None = None,
    max_files_scanned: int = 200,
) -> _SearchInFileTool:
    """Build a search tool whose folder listing and per-file downloads are mocked.

    `contents` maps a file URL to raw bytes; a missing URL or an Exception value
    raises (oversized -> ValueError, binary -> raw bytes that fail UTF-8 decode).
    """
    service = make_service()
    if list_side_effect:
        service.list_folder.side_effect = list_side_effect
    else:
        service.list_folder.return_value = entries

    async def _download(url: str):
        value = contents[url]
        if isinstance(value, Exception):
            raise value
        return value, None

    service.download_file.side_effect = _download
    return _build(service, max_files_scanned=max_files_scanned)


class TestSearchFileMode:
    @pytest.mark.asyncio
    async def test_relative_path_resolves(self):
        tool = _make_tool("a\nb\nc")
        await tool._run_in_stage_async(stage_wrapper=None, path="x.md", pattern="b")
        tool._dial_file_service.download_file.assert_awaited_once_with("files/appbucket/x.md")

    @pytest.mark.asyncio
    async def test_absolute_path_passes_through(self):
        tool = _make_tool("a\nb\nc")
        await tool._run_in_stage_async(stage_wrapper=None, path="files/o/x.md", pattern="b")
        tool._dial_file_service.download_file.assert_awaited_once_with("files/o/x.md")

    @pytest.mark.asyncio
    async def test_single_match(self):
        tool = _make_tool("foo\nbar\nbaz")
        result = await tool._run_in_stage_async(stage_wrapper=None, path="x", pattern="bar")
        assert result.content == code_block("2:bar")

    @pytest.mark.asyncio
    async def test_no_matches(self):
        tool = _make_tool("foo\nbar")
        result = await tool._run_in_stage_async(stage_wrapper=None, path="x", pattern="zzz")
        assert result.content == "No matches found."

    @pytest.mark.asyncio
    async def test_case_insensitive(self):
        tool = _make_tool("Hello\nworld")
        result = await tool._run_in_stage_async(
            stage_wrapper=None, path="x", pattern="hello", case_insensitive=True
        )
        assert "Hello" in result.content

    @pytest.mark.asyncio
    async def test_context_lines_separate_windows(self):
        # Matches far enough apart that their context windows do not merge.
        tool = _make_tool("ERR\na\nb\nc\nERR")
        result = await tool._run_in_stage_async(
            stage_wrapper=None, path="x", pattern="ERR", context_lines=1
        )
        assert result.content == code_block("1:ERR\n2:a\n--\n4:c\n5:ERR")

    @pytest.mark.asyncio
    async def test_context_lines_adjacent_windows_merge(self):
        # Adjacent windows (gap <= 2*context) merge into one block (no '--').
        tool = _make_tool("a\nERR\nb\nc\nERR\nd")
        result = await tool._run_in_stage_async(
            stage_wrapper=None, path="x", pattern="ERR", context_lines=1
        )
        assert result.content == code_block("1:a\n2:ERR\n3:b\n4:c\n5:ERR\n6:d")

    @pytest.mark.asyncio
    async def test_output_mode_in_file_mode_ignored(self):
        # Folder-only params are silently ignored in file mode, not rejected.
        tool = _make_tool("a\nb")
        result = await tool._run_in_stage_async(
            stage_wrapper=None, path="x", pattern="a", output_mode="count"
        )
        assert result.content == code_block("1:a")

    @pytest.mark.asyncio
    async def test_name_filter_in_file_mode_ignored(self):
        tool = _make_tool("a\nb")
        result = await tool._run_in_stage_async(
            stage_wrapper=None, path="x", pattern="a", name_filter="*.md"
        )
        assert result.content == code_block("1:a")

    @pytest.mark.asyncio
    async def test_max_depth_in_file_mode_ignored(self):
        tool = _make_tool("foo\nbar")
        result = await tool._run_in_stage_async(
            stage_wrapper=None, path="x", pattern="bar", max_depth=3
        )
        assert result.content == code_block("2:bar")


class TestSearchFolderMode:
    @pytest.mark.asyncio
    async def test_root_reference_searches_whole_home(self):
        entries = [_file("files/appbucket/a.md"), _file("files/appbucket/sub/b.md")]
        contents = {
            "files/appbucket/a.md": b"hello\nERROR here",
            "files/appbucket/sub/b.md": b"nothing",
        }
        tool = _make_folder_tool(entries, contents)
        result = await tool._run_in_stage_async(stage_wrapper=None, path="", pattern="ERROR")
        tool._dial_file_service.list_folder.assert_awaited_once_with(
            "files/appbucket/", max_depth=10
        )
        assert result.content == code_block("a.md\n2:ERROR here")

    @pytest.mark.asyncio
    async def test_content_mode_groups_matches_per_file(self):
        entries = [_file("files/appbucket/a.md"), _file("files/appbucket/b.txt")]
        contents = {
            "files/appbucket/a.md": b"ERROR one\nok",
            "files/appbucket/b.txt": b"ok\nERROR two",
        }
        tool = _make_folder_tool(entries, contents)
        result = await tool._run_in_stage_async(
            stage_wrapper=None, path="reports/", pattern="ERROR"
        )
        assert result.content == code_block("a.md\n1:ERROR one\n\nb.txt\n2:ERROR two")

    @pytest.mark.asyncio
    async def test_files_with_matches_mode(self):
        entries = [_file("files/appbucket/a.md"), _file("files/appbucket/b.txt")]
        contents = {
            "files/appbucket/a.md": b"ERROR",
            "files/appbucket/b.txt": b"clean",
        }
        tool = _make_folder_tool(entries, contents)
        result = await tool._run_in_stage_async(
            stage_wrapper=None, path="reports/", pattern="ERROR", output_mode="files_with_matches"
        )
        assert result.content == code_block("a.md")

    @pytest.mark.asyncio
    async def test_count_mode_is_rejected(self):
        # 'count' was dropped; only 'content' and 'files_with_matches' remain.
        tool = _make_folder_tool([], {})
        with pytest.raises(InvalidToolCallParameterException) as exc:
            await tool._run_in_stage_async(
                stage_wrapper=None, path="reports/", pattern="ERROR", output_mode="count"
            )
        assert exc.value.parameter_name == "output_mode"

    @pytest.mark.asyncio
    async def test_non_utf8_file_skipped(self):
        entries = [_file("files/appbucket/a.bin"), _file("files/appbucket/b.md")]
        contents = {
            "files/appbucket/a.bin": b"\xff\xfe\x00binary",
            "files/appbucket/b.md": b"ERROR text",
        }
        tool = _make_folder_tool(entries, contents)
        result = await tool._run_in_stage_async(stage_wrapper=None, path="d/", pattern="ERROR")
        assert result.content == code_block("b.md\n1:ERROR text")

    @pytest.mark.asyncio
    async def test_oversized_file_skipped(self):
        entries = [_file("files/appbucket/big.md"), _file("files/appbucket/b.md")]
        contents = {
            "files/appbucket/big.md": ValueError("File size exceeds the limit"),
            "files/appbucket/b.md": b"ERROR text",
        }
        tool = _make_folder_tool(entries, contents)
        result = await tool._run_in_stage_async(stage_wrapper=None, path="d/", pattern="ERROR")
        assert result.content == code_block("b.md\n1:ERROR text")

    @pytest.mark.asyncio
    async def test_name_filter_excludes_before_download(self):
        entries = [
            _file("files/appbucket/data/a.csv"),
            _file("files/appbucket/data/b.json"),
        ]
        contents = {"files/appbucket/data/a.csv": b"2026-Q1 row"}
        tool = _make_folder_tool(entries, contents)
        result = await tool._run_in_stage_async(
            stage_wrapper=None, path="data/", pattern="2026-Q1", name_filter="**/*.csv"
        )
        assert result.content == code_block("data/a.csv\n1:2026-Q1 row")
        # The .json was filtered out before any download was attempted.
        tool._dial_file_service.download_file.assert_awaited_once_with("files/appbucket/data/a.csv")

    @pytest.mark.asyncio
    async def test_max_depth_passed_to_list_folder(self):
        tool = _make_folder_tool([], {})
        await tool._run_in_stage_async(stage_wrapper=None, path="data/", pattern="x", max_depth=2)
        tool._dial_file_service.list_folder.assert_awaited_once_with(
            "files/appbucket/data/", max_depth=2
        )

    @pytest.mark.asyncio
    async def test_max_depth_out_of_range_raises(self):
        tool = _make_folder_tool([], {})
        with pytest.raises(InvalidToolCallParameterException) as exc:
            await tool._run_in_stage_async(
                stage_wrapper=None, path="data/", pattern="x", max_depth=11
            )
        assert exc.value.parameter_name == "max_depth"

    @pytest.mark.asyncio
    async def test_invalid_output_mode_raises(self):
        tool = _make_folder_tool([], {})
        with pytest.raises(InvalidToolCallParameterException) as exc:
            await tool._run_in_stage_async(
                stage_wrapper=None, path="data/", pattern="x", output_mode="bogus"
            )
        assert exc.value.parameter_name == "output_mode"

    @pytest.mark.asyncio
    async def test_file_cap_truncation_appends_notice(self):
        cap = 3
        n = cap + 2
        entries = [_file(f"files/appbucket/f{i}.txt") for i in range(n)]
        contents = {f"files/appbucket/f{i}.txt": b"ERROR" for i in range(n)}
        tool = _make_folder_tool(entries, contents, max_files_scanned=cap)
        result = await tool._run_in_stage_async(stage_wrapper=None, path="d/", pattern="ERROR")
        assert "search truncated" in result.content
        assert f"after {cap} files scanned" in result.content
        # Exactly `cap` downloads were attempted, no more.
        assert tool._dial_file_service.download_file.await_count == cap

    @pytest.mark.asyncio
    async def test_not_a_folder_raises(self):
        # Folder mode inherits the shared _list_folder_entries "not a folder" policy.
        tool = _make_folder_tool([], {}, list_side_effect=ValueError("not a folder"))
        with pytest.raises(InvalidToolCallParameterException) as exc:
            await tool._run_in_stage_async(stage_wrapper=None, path="afile/", pattern="x")
        assert exc.value.parameter_name == "path"
        assert "not a folder" in exc.value.message

    @pytest.mark.asyncio
    async def test_folder_without_trailing_slash_is_file_mode(self):
        # 'reports' (no slash) selects file mode; the folder URL fails to download.
        service = make_service()
        service.download_file.side_effect = ResourceNotFoundError(message="404")
        tool = _build(service)
        with pytest.raises(InvalidToolCallParameterException) as exc:
            await tool._run_in_stage_async(stage_wrapper=None, path="reports", pattern="x")
        assert exc.value.parameter_name == "path"
        assert "file not found: reports" in exc.value.message

    @pytest.mark.asyncio
    async def test_non_root_folder_not_found_raises(self):
        tool = _make_folder_tool([], {}, list_side_effect=ResourceNotFoundError(message="404"))
        with pytest.raises(InvalidToolCallParameterException) as exc:
            await tool._run_in_stage_async(stage_wrapper=None, path="missing/", pattern="x")
        assert exc.value.parameter_name == "path"
        assert "folder not found: missing/" in exc.value.message

    @pytest.mark.asyncio
    async def test_root_reference_missing_returns_no_matches(self):
        tool = _make_folder_tool([], {}, list_side_effect=ResourceNotFoundError(message="404"))
        result = await tool._run_in_stage_async(stage_wrapper=None, path="", pattern="x")
        assert result.content == "No matches found."

    @pytest.mark.asyncio
    async def test_no_matches_in_folder(self):
        entries = [_file("files/appbucket/a.md")]
        contents = {"files/appbucket/a.md": b"clean content"}
        tool = _make_folder_tool(entries, contents)
        result = await tool._run_in_stage_async(stage_wrapper=None, path="d/", pattern="ERROR")
        assert result.content == "No matches found."
