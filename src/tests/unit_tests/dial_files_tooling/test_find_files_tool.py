import pytest
from aidial_client._exception import ResourceNotFoundError

from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.dial_core_services.dial_file_service import FolderEntry
from quickapp.dial_files_tooling._find_files_tool import _FindFilesTool
from quickapp.dial_files_tooling._tool_configs import FIND_FILES_TOOL_CONFIG
from tests.unit_tests.dial_files_tooling._helpers import make_service, make_tool


def _file(url: str, size: int = 10) -> FolderEntry:
    return FolderEntry(url=url, is_folder=False, size=size)


def _folder(url: str) -> FolderEntry:
    return FolderEntry(url=url, is_folder=True, size=None)


def _make_tool(
    entries: list[FolderEntry] | None = None, side_effect: Exception | None = None
) -> _FindFilesTool:
    service = make_service()
    if side_effect:
        service.list_folder.side_effect = side_effect
    else:
        service.list_folder.return_value = entries or []
    return make_tool(_FindFilesTool, FIND_FILES_TOOL_CONFIG, service=service)


class TestFindFiles:
    @pytest.mark.asyncio
    async def test_double_star_matches_at_any_depth_including_root(self):
        entries = [
            _file("files/appbucket/a.csv"),
            _file("files/appbucket/x/y/b.csv"),
            _file("files/appbucket/notes.txt"),
        ]
        tool = _make_tool(entries=entries)
        result = await tool._run_in_stage_async(stage_wrapper=None, pattern="**/*.csv")
        assert "a.csv" in result.content
        assert "x/y/b.csv" in result.content
        assert "notes.txt" not in result.content

    @pytest.mark.asyncio
    async def test_default_path_searches_home_root(self):
        tool = _make_tool(entries=[])
        await tool._run_in_stage_async(stage_wrapper=None, pattern="*.csv")
        tool._dial_file_service.list_folder.assert_awaited_once_with(
            "files/appbucket/", max_depth=10
        )

    @pytest.mark.asyncio
    async def test_single_star_does_not_cross_slash(self):
        entries = [
            _file("files/appbucket/a.csv"),
            _file("files/appbucket/x/b.csv"),
        ]
        tool = _make_tool(entries=entries)
        result = await tool._run_in_stage_async(stage_wrapper=None, pattern="*.csv")
        assert "a.csv" in result.content
        assert "x/b.csv" not in result.content

    @pytest.mark.asyncio
    async def test_question_mark_single_char(self):
        entries = [
            _file("files/appbucket/a1.txt"),
            _file("files/appbucket/a12.txt"),
        ]
        tool = _make_tool(entries=entries)
        result = await tool._run_in_stage_async(stage_wrapper=None, pattern="a?.txt")
        assert "a1.txt" in result.content
        assert "a12.txt" not in result.content

    @pytest.mark.asyncio
    async def test_subfolder_pattern_relative_to_search_root(self):
        # UC-6: glob is matched against the path relative to the search root.
        entries = [_file("files/appbucket/reports/report-1.md")]
        tool = _make_tool(entries=entries)
        result = await tool._run_in_stage_async(
            stage_wrapper=None, path="reports/", pattern="report-*.md", max_depth=2
        )
        tool._dial_file_service.list_folder.assert_awaited_once_with(
            "files/appbucket/reports/", max_depth=2
        )
        # Output uses the home-relative display path.
        assert "reports/report-1.md" in result.content

    @pytest.mark.asyncio
    async def test_max_depth_out_of_range_raises(self):
        tool = _make_tool(entries=[])
        with pytest.raises(InvalidToolCallParameterException) as exc:
            await tool._run_in_stage_async(stage_wrapper=None, pattern="*.csv", max_depth=11)
        assert exc.value.parameter_name == "max_depth"

    @pytest.mark.asyncio
    async def test_max_depth_zero_raises(self):
        tool = _make_tool(entries=[])
        with pytest.raises(InvalidToolCallParameterException):
            await tool._run_in_stage_async(stage_wrapper=None, pattern="*.csv", max_depth=0)

    @pytest.mark.asyncio
    async def test_root_reference_missing_returns_no_files(self):
        tool = _make_tool(side_effect=ResourceNotFoundError(message="404"))
        result = await tool._run_in_stage_async(stage_wrapper=None, pattern="*.csv", path="")
        assert result.content == "No files found."

    @pytest.mark.asyncio
    async def test_non_root_folder_not_found_raises(self):
        tool = _make_tool(side_effect=ResourceNotFoundError(message="404"))
        with pytest.raises(InvalidToolCallParameterException) as exc:
            await tool._run_in_stage_async(stage_wrapper=None, pattern="*.csv", path="missing/")
        assert exc.value.parameter_name == "path"
        assert "folder not found: missing/" in exc.value.message
        assert "appbucket" not in exc.value.message

    @pytest.mark.asyncio
    async def test_no_matches_returns_no_files(self):
        tool = _make_tool(entries=[_file("files/appbucket/a.txt")])
        result = await tool._run_in_stage_async(stage_wrapper=None, pattern="*.csv")
        assert result.content == "No files found."

    @pytest.mark.asyncio
    async def test_matched_folder_renders_with_dash_size(self):
        entries = [_folder("files/appbucket/logs/")]
        tool = _make_tool(entries=entries)
        result = await tool._run_in_stage_async(stage_wrapper=None, pattern="logs/")
        assert "logs/" in result.content
        # Folders render with size '-' via the shared listing renderer.
        assert "NAME" in result.content
        assert "SIZE" in result.content
