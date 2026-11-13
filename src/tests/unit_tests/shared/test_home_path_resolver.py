import pytest

from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.common.project_context import ProjectContext
from quickapp.shared.home_path.home_path_resolver import HomePathResolver
from tests.unit_tests.dial_files_tooling._helpers import make_config, make_service


def _resolver(
    agent_home_dir: str = "",
    appdata: str | None = "appbucket",
    project: ProjectContext | None = None,
) -> HomePathResolver:
    return HomePathResolver(
        dial_file_service=make_service(appdata=appdata),
        dial_files_config=make_config(agent_home_dir),
        project=project,
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


_PROJECT = ProjectContext(url="projects/user-bucket/My Project")
_ARTIFACTS = "projects/user-bucket/My%20Project/files/artifacts/"
_CONTEXT_FILE = "projects/user-bucket/My%20Project/files/context/tickets.csv"


class TestProjectHome:
    @pytest.mark.asyncio
    async def test_home_is_artifacts_and_ignores_agent_home_dir(self):
        resolver = _resolver(agent_home_dir="workspace/", project=_PROJECT)
        assert await resolver.resolve_home_dir() == _ARTIFACTS

    @pytest.mark.asyncio
    async def test_home_skips_appdata_lookup(self):
        service = make_service()
        resolver = HomePathResolver(service, make_config(), _PROJECT)
        await resolver.resolve_home_dir()
        service.my_appdata_home.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_relative_path_resolves_under_artifacts(self):
        url = await _resolver(project=_PROJECT).resolve_appdata_url("my notes/a.md")
        assert url == f"{_ARTIFACTS}my%20notes/a.md"

    @pytest.mark.asyncio
    async def test_current_project_url_is_absolute(self):
        url = "projects/user-bucket/My Project/files/context/tickets.csv"
        assert await _resolver(project=_PROJECT).resolve_appdata_url(url) == _CONTEXT_FILE

    @pytest.mark.parametrize(
        "path",
        [
            "projects/user-bucket/Other/files/x.md",
            "projects/user-bucket/",
            "projects/user-bucket/My Project/x.md",
        ],
    )
    @pytest.mark.asyncio
    async def test_other_projects_url_is_rejected(self, path):
        with pytest.raises(InvalidToolCallParameterException) as excinfo:
            await _resolver(project=_PROJECT).resolve_appdata_url(path)
        assert "current project" in excinfo.value.message

    @pytest.mark.asyncio
    async def test_projects_url_is_rejected_without_project(self):
        with pytest.raises(InvalidToolCallParameterException):
            await _resolver().resolve_appdata_url("projects/user-bucket/My Project/files/x.md")

    @pytest.mark.asyncio
    async def test_files_url_still_absolute_in_project(self):
        url = await _resolver(project=_PROJECT).resolve_appdata_url("files/appbucket/x.md")
        assert url == "files/appbucket/x.md"

    @pytest.mark.asyncio
    async def test_display_path_relative_to_artifacts(self):
        resolver = _resolver(project=_PROJECT)
        assert await resolver.to_display_path(f"{_ARTIFACTS}a/b.md") == "a/b.md"
        decoded = "projects/user-bucket/My Project/files/artifacts/a.md"
        assert await resolver.to_display_path(decoded) == "a.md"

    @pytest.mark.asyncio
    async def test_display_path_shows_project_files_decoded(self):
        resolver = _resolver(project=_PROJECT)
        decoded = "projects/user-bucket/My Project/files/context/tickets.csv"
        assert await resolver.to_display_path(_CONTEXT_FILE) == decoded
        assert await resolver.to_display_path(f"{_ARTIFACTS}my%20notes/a.md") == "my notes/a.md"

    @pytest.mark.asyncio
    async def test_display_path_keeps_names_that_dont_round_trip_encoded(self):
        # A literal `%41` in a name would decode to `A` when passed back.
        url = f"{_ARTIFACTS}100%2541.md"
        assert await _resolver(project=_PROJECT).to_display_path(url) == "100%2541.md"

    @pytest.mark.asyncio
    async def test_decoded_display_path_resolves_back(self):
        resolver = _resolver(project=_PROJECT)
        display = await resolver.to_display_path(_CONTEXT_FILE)
        assert await resolver.resolve_appdata_url(display) == _CONTEXT_FILE

    @pytest.mark.parametrize("path", ["%2e%2e/PROJECT.md", ".%2e/x", "a%2F..%2Fb", "a//b"])
    @pytest.mark.asyncio
    async def test_unsafe_relative_path_is_rejected_before_decoding(self, path):
        with pytest.raises(InvalidToolCallParameterException) as excinfo:
            await _resolver(project=_PROJECT).resolve_appdata_url(path)
        assert excinfo.value.parameter_name == "path"

    def test_is_absolute(self):
        resolver = _resolver(project=_PROJECT)
        assert resolver.is_absolute("files/appbucket/x.md")
        assert resolver.is_absolute(_CONTEXT_FILE)
        assert resolver.is_absolute("projects/user-bucket/Other/files/x.md")
        assert _resolver().is_absolute(_CONTEXT_FILE)
        assert not resolver.is_absolute("reports/projects/a.md")


class TestResolveHandoffUrl:
    @pytest.mark.parametrize(
        "path, expected",
        [
            ("projects/user-bucket/My Project/files/context/tickets.csv", _CONTEXT_FILE),
            (f"{_ARTIFACTS}report.pdf", f"{_ARTIFACTS}report.pdf"),
            ("files/other-bucket/shared/a.pdf", "files/other-bucket/shared/a.pdf"),
            (
                "https://dial.example.com/v1/files/other-bucket/a.pdf",
                "https://dial.example.com/v1/files/other-bucket/a.pdf",
            ),
        ],
    )
    def test_readable_and_non_project_urls_pass(self, path, expected):
        resolver = _resolver(project=_PROJECT)
        assert resolver.resolve_handoff_url("attachment_urls", path) == expected

    @pytest.mark.parametrize(
        "path",
        [
            "projects/user-bucket/My Project/files/conversations/chat.json",
            "projects/user-bucket/My Project/files/PROJECT.md",
            "projects/user-bucket/My Project/files/",
            "projects/user-bucket/Other/files/context/a.csv",
        ],
    )
    def test_project_urls_outside_context_and_artifacts_are_refused(self, path):
        with pytest.raises(InvalidToolCallParameterException) as excinfo:
            _resolver(project=_PROJECT).resolve_handoff_url("attachment_urls", path)
        assert excinfo.value.parameter_name == "attachment_urls"
        assert "context/ or artifacts/" in excinfo.value.message

    def test_project_url_is_refused_without_project(self):
        with pytest.raises(InvalidToolCallParameterException):
            _resolver().resolve_handoff_url("doc_url", _CONTEXT_FILE)

    def test_files_url_unchanged_without_project(self):
        assert _resolver().resolve_handoff_url("doc_url", "files/appbucket/x.md") == (
            "files/appbucket/x.md"
        )


class TestResolveWriteUrl:
    @pytest.mark.parametrize(
        "path",
        [
            "files/x/a.md",
            _CONTEXT_FILE,
            _PROJECT.instructions_url,
            f"{_ARTIFACTS}a.md",
            "projects/user-bucket/Other/files/a.md",
        ],
    )
    @pytest.mark.asyncio
    async def test_absolute_url_rejected(self, path):
        with pytest.raises(InvalidToolCallParameterException) as exc:
            await _resolver(project=_PROJECT).resolve_write_url("destination", path)
        assert exc.value.parameter_name == "destination"
        assert "relative path" in exc.value.message

    @pytest.mark.asyncio
    async def test_absolute_url_rejected_without_project(self):
        with pytest.raises(InvalidToolCallParameterException):
            await _resolver().resolve_write_url("path", "files/x/a.md")

    @pytest.mark.asyncio
    async def test_relative_path_resolves_under_the_home(self):
        url = await _resolver(project=_PROJECT).resolve_write_url("path", "reports/a.md")

        assert url == f"{_ARTIFACTS}reports/a.md"
