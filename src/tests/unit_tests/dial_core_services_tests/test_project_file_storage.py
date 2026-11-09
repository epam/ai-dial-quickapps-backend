from unittest.mock import MagicMock

import pytest

from quickapp.dial_core_services._project_files import ProjectFilesClient
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

PROJECT_FILE = "projects/b/p/files/context/a.csv"


def _make_storage(project_files: MagicMock) -> ProjectFileStorage:
    return ProjectFileStorage(project_files, MagicMock(spec=FileLoadingSizeLimitResolver))


class TestDownload:
    @pytest.mark.asyncio
    async def test_streams_the_file_and_builds_its_metadata(self):
        project_files = MagicMock(spec=ProjectFilesClient)
        project_files.stream = project_stream(b"project", etag="file-etag")

        data, metadata = await _make_storage(project_files).download(PROJECT_FILE, 100)

        assert data == b"project"
        assert metadata.etag == "file-etag"
        assert metadata.content_length == len(b"project")
        project_files.stream.assert_called_once_with(PROJECT_FILE)

    @pytest.mark.asyncio
    async def test_over_the_limit_is_rejected(self):
        project_files = MagicMock(spec=ProjectFilesClient)
        project_files.stream = project_stream(b"x" * 11)

        with pytest.raises(FileTooLargeError, match="exceeds the limit"):
            await _make_storage(project_files).download(PROJECT_FILE, 10)


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
