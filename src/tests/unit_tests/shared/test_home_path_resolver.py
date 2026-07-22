import pytest

from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.dial_files_tooling._utils import reject_absolute_path
from quickapp.shared.home_path.home_path_resolver import HomePathResolver
from tests.unit_tests.dial_files_tooling._helpers import make_config, make_service


def _resolver(agent_home_dir: str = "", appdata: str | None = "appbucket") -> HomePathResolver:
    return HomePathResolver(
        dial_file_service=make_service(appdata=appdata),
        dial_files_config=make_config(agent_home_dir),
    )


class TestResolveAppdataUrl:
    @pytest.mark.asyncio
    async def test_relative_path_joined_with_home(self):
        url = await _resolver().resolve_appdata_url("reports/summary.md")
        assert url == "files/appbucket/reports/summary.md"

    @pytest.mark.asyncio
    async def test_subdir_home_prepended(self):
        url = await _resolver(agent_home_dir="workspace/").resolve_appdata_url("reports/summary.md")
        assert url == "files/appbucket/workspace/reports/summary.md"

    @pytest.mark.asyncio
    async def test_absolute_url_passes_through(self):
        url = await _resolver().resolve_appdata_url("files/otherbucket/uploads/notes.txt")
        assert url == "files/otherbucket/uploads/notes.txt"

    @pytest.mark.asyncio
    async def test_newline_in_relative_path_rejected(self):
        with pytest.raises(InvalidToolCallParameterException) as exc:
            await _resolver().resolve_appdata_url("foo\nbar")
        assert exc.value.parameter_name == "path"

    @pytest.mark.asyncio
    async def test_newline_in_absolute_url_rejected(self):
        with pytest.raises(InvalidToolCallParameterException) as exc:
            await _resolver().resolve_appdata_url("files/x/foo\nbar")
        assert exc.value.parameter_name == "path"

    @pytest.mark.asyncio
    async def test_empty_path_rejected(self):
        with pytest.raises(InvalidToolCallParameterException):
            await _resolver().resolve_appdata_url("")

    @pytest.mark.asyncio
    async def test_leading_slash_rejected(self):
        with pytest.raises(InvalidToolCallParameterException):
            await _resolver().resolve_appdata_url("/abs.md")

    @pytest.mark.asyncio
    async def test_dotdot_segment_rejected(self):
        with pytest.raises(InvalidToolCallParameterException):
            await _resolver().resolve_appdata_url("../escape.md")

    @pytest.mark.asyncio
    async def test_dotdot_substring_rejected(self):
        with pytest.raises(InvalidToolCallParameterException):
            await _resolver().resolve_appdata_url("a/../b")

    @pytest.mark.asyncio
    async def test_empty_segment_rejected(self):
        with pytest.raises(InvalidToolCallParameterException):
            await _resolver().resolve_appdata_url("a//b")

    @pytest.mark.asyncio
    async def test_trailing_whitespace_rejected(self):
        with pytest.raises(InvalidToolCallParameterException):
            await _resolver().resolve_appdata_url("notes.md ")

    @pytest.mark.asyncio
    async def test_no_appdata_raises(self):
        with pytest.raises(InvalidToolCallParameterException) as exc:
            await _resolver(appdata=None).resolve_appdata_url("notes.md")
        assert "appdata" in exc.value.message

    @pytest.mark.asyncio
    async def test_folder_trailing_slash_preserved(self):
        url = await _resolver().resolve_appdata_url("reports/")
        assert url == "files/appbucket/reports/"


class TestToDisplayPath:
    @pytest.mark.asyncio
    async def test_home_url_becomes_relative(self):
        display = await _resolver().to_display_path("files/appbucket/reports/summary.md")
        assert display == "reports/summary.md"

    @pytest.mark.asyncio
    async def test_out_of_home_url_unchanged(self):
        url = "files/otherbucket/x.md"
        display = await _resolver().to_display_path(url)
        assert display == url

    @pytest.mark.asyncio
    async def test_home_url_itself_becomes_empty(self):
        display = await _resolver().to_display_path("files/appbucket/")
        assert display == ""


class TestRejectAbsolutePath:
    def test_absolute_url_rejected(self):
        with pytest.raises(InvalidToolCallParameterException) as exc:
            reject_absolute_path("path", "write_file", "files/x/a.md")
        assert exc.value.parameter_name == "path"
        assert "relative" in exc.value.message

    def test_relative_path_allowed(self):
        reject_absolute_path("path", "write_file", "reports/a.md")  # no raise
