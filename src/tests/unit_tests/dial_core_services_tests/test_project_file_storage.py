from unittest.mock import AsyncMock, MagicMock

import pytest
from aidial_client import DialException

from quickapp.common.project_context import ProjectContext
from quickapp.dial_core_services._project_files import ProjectFilesClient, ProjectItem
from quickapp.dial_core_services.exceptions import FileTooLargeError
from quickapp.dial_core_services.storage._project_file_storage import (
    ProjectFileStorage,
    read_within_size_limit,
)
from quickapp.shared.config_resolvers.file_loading_size_limit_resolver import (
    FileLoadingSizeLimitResolver,
)
from tests.unit_tests.dial_core_services_tests._project_stream import (
    project_stream,
    streamed_response,
)

PROJECT = ProjectContext(url="projects/b/p")
PROJECT_FILE = "projects/b/p/files/context/a.csv"
ROOT = "projects/b/p/files/"


def _make_storage(
    project_files: MagicMock,
    size_limit: int = 100,
    project: ProjectContext | None = PROJECT,
) -> ProjectFileStorage:
    resolver = MagicMock(spec=FileLoadingSizeLimitResolver)
    resolver.resolve.return_value = size_limit
    return ProjectFileStorage(project_files, resolver, project)


class TestDownload:
    @pytest.mark.asyncio
    async def test_streams_the_file_and_builds_its_metadata(self):
        project_files = MagicMock(spec=ProjectFilesClient)
        project_files.stream = project_stream(b"project", etag="file-etag")

        data, metadata = await _make_storage(project_files).download(PROJECT_FILE)

        assert data == b"project"
        assert metadata.etag == "file-etag"
        assert metadata.content_length == len(b"project")
        project_files.stream.assert_called_once_with(PROJECT_FILE)

    @pytest.mark.asyncio
    async def test_over_the_limit_is_rejected(self):
        project_files = MagicMock(spec=ProjectFilesClient)
        project_files.stream = project_stream(b"x" * 11)

        with pytest.raises(FileTooLargeError, match="exceeds the limit"):
            await _make_storage(project_files, size_limit=10).download(PROJECT_FILE)


class TestAgentView:
    @pytest.mark.parametrize(
        "url",
        [
            f"{ROOT}PROJECT.md",
            f"{ROOT}conversations/chat.json",
            f"{ROOT}other/a.md",
            f"{ROOT}context/../conversations/chat.json",
        ],
    )
    @pytest.mark.asyncio
    async def test_a_file_outside_context_and_artifacts_is_refused_before_any_request(self, url):
        project_files = MagicMock(spec=ProjectFilesClient)
        project_files.stream = project_stream(b"secret")

        with pytest.raises(DialException) as excinfo:
            await _make_storage(project_files).download(url)

        assert excinfo.value.status_code == 403
        project_files.stream.assert_not_called()

    @pytest.mark.parametrize("url", [f"{ROOT}conversations/", f"{ROOT}other/"])
    @pytest.mark.asyncio
    async def test_a_folder_outside_context_and_artifacts_is_not_listed(self, url):
        project_files = MagicMock(spec=ProjectFilesClient)
        project_files.list = AsyncMock(return_value=[])

        with pytest.raises(DialException) as excinfo:
            await _make_storage(project_files).list_level(url)

        assert excinfo.value.status_code == 403
        project_files.list.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_the_project_folder_lists_only_context_and_artifacts(self):
        project_files = MagicMock(spec=ProjectFilesClient)
        project_files.list = AsyncMock(
            return_value=[
                ProjectItem(url=f"{ROOT}PROJECT.md", is_folder=False),
                ProjectItem(url=f"{ROOT}context/", is_folder=True),
                ProjectItem(url=f"{ROOT}conversations/", is_folder=True),
                ProjectItem(url=f"{ROOT}artifacts/", is_folder=True),
            ]
        )

        entries = await _make_storage(project_files).list_level(ROOT)

        assert [entry.url for entry in entries] == [f"{ROOT}context/", f"{ROOT}artifacts/"]

    @pytest.mark.parametrize("folder", [f"{ROOT}context/", f"{ROOT}artifacts/sub/"])
    @pytest.mark.asyncio
    async def test_context_and_artifacts_folders_are_listed_as_is(self, folder):
        project_files = MagicMock(spec=ProjectFilesClient)
        project_files.list = AsyncMock(
            return_value=[ProjectItem(url=f"{folder}a.md", is_folder=False)]
        )

        entries = await _make_storage(project_files).list_level(folder)

        assert [entry.url for entry in entries] == [f"{folder}a.md"]
        project_files.list.assert_awaited_once_with(folder)

    @pytest.mark.asyncio
    async def test_copy_from_a_conversation_is_refused_without_writing(self):
        project_files = MagicMock(spec=ProjectFilesClient)
        project_files.stream = project_stream(b"secret")
        project_files.put = AsyncMock()

        with pytest.raises(DialException) as excinfo:
            await _make_storage(project_files).copy(
                f"{ROOT}conversations/chat.json", f"{ROOT}artifacts/chat.json", overwrite=True
            )

        assert excinfo.value.status_code == 403
        project_files.put.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_without_a_project_nothing_is_readable(self):
        project_files = MagicMock(spec=ProjectFilesClient)
        project_files.stream = project_stream(b"data")

        with pytest.raises(DialException):
            await _make_storage(project_files, project=None).download(PROJECT_FILE)


class TestReadInstructions:
    @pytest.mark.asyncio
    async def test_reads_project_md_although_the_agent_cannot(self):
        project_files = MagicMock(spec=ProjectFilesClient)
        project_files.stream = project_stream(b"# Instructions")

        data, _ = await _make_storage(project_files).read_instructions()

        assert data == b"# Instructions"
        project_files.stream.assert_called_once_with(PROJECT.instructions_url)

    @pytest.mark.asyncio
    async def test_over_the_limit_is_rejected(self):
        project_files = MagicMock(spec=ProjectFilesClient)
        project_files.stream = project_stream(b"x" * 11)

        with pytest.raises(FileTooLargeError):
            await _make_storage(project_files, size_limit=10).read_instructions()


class TestReadWithinSizeLimit:
    @pytest.mark.asyncio
    async def test_content_length_over_the_limit_is_rejected_before_the_body(self):
        response, stream = streamed_response([b"x" * 11], content_length=11)

        with pytest.raises(FileTooLargeError, match="exceeds the limit of 10"):
            await read_within_size_limit(response, "projects/b/p/files/a.bin", 10)
        assert stream.read_chunks == 0

    @pytest.mark.asyncio
    async def test_without_content_length_reading_stops_past_the_limit(self):
        response, stream = streamed_response([b"x" * 6, b"x" * 6, b"x" * 6])

        with pytest.raises(FileTooLargeError, match="exceeds the limit of 10"):
            await read_within_size_limit(response, "projects/b/p/files/a.bin", 10)
        assert stream.read_chunks == 2

    @pytest.mark.asyncio
    async def test_within_the_limit_returns_the_bytes_and_metadata(self):
        response, _ = streamed_response(
            [b"hel", b"lo"], content_length=5, etag="file-etag", content_type="text/plain"
        )

        data, metadata = await read_within_size_limit(response, "projects/b/p/files/notes.md", 10)

        assert data == b"hello"
        assert metadata.url == "projects/b/p/files/notes.md"
        assert metadata.name == "notes.md"
        assert metadata.bucket == "b"
        assert metadata.etag == "file-etag"
        assert metadata.content_type == "text/plain"
        assert metadata.content_length == 5
