from unittest.mock import AsyncMock, MagicMock

import pytest

from quickapp.common.project_context import ProjectContext
from quickapp.dial_core_services._project_files import ProjectFilesClient
from quickapp.dial_core_services.dial_downloader import DialDownloader, read_within_size_limit
from quickapp.dial_core_services.exceptions import FileTooLargeError
from quickapp.shared.config_resolvers.file_loading_size_limit_resolver import (
    FileLoadingSizeLimitResolver,
)
from tests.unit_tests.dial_core_services_tests._project_stream import (
    project_stream,
    streamed_response,
)

DEFAULT_LIMIT = 10 * 1024 * 1024


def _make_mock_dial_client(
    content_length: int = 100,
    file_content: bytes = b"file content",
) -> MagicMock:
    metadata = MagicMock()
    metadata.content_length = content_length

    download_result = MagicMock()
    download_result.aget_content = AsyncMock(return_value=file_content)

    files = MagicMock()
    files.get_metadata = AsyncMock(return_value=metadata)
    files.download = AsyncMock(return_value=download_result)

    client = MagicMock()
    client.files = files
    return client


def _make_resolver(size_limit: int = DEFAULT_LIMIT) -> MagicMock:
    resolver = MagicMock(spec=FileLoadingSizeLimitResolver)
    resolver.resolve.return_value = size_limit
    return resolver


def _make_downloader(
    dial_client: MagicMock | None = None,
    size_limit_resolver: MagicMock | None = None,
    project_files: MagicMock | None = None,
    project: ProjectContext | None = None,
) -> DialDownloader:
    return DialDownloader(
        dial_client=dial_client or _make_mock_dial_client(),
        size_limit_resolver=size_limit_resolver or _make_resolver(),
        project_files=project_files or MagicMock(spec=ProjectFilesClient),
        project=project,
    )


@pytest.mark.asyncio
async def test_fetch_returns_bytes_and_metadata():
    client = _make_mock_dial_client(content_length=100, file_content=b"hello")
    downloader = _make_downloader(dial_client=client)

    data, metadata = await downloader.fetch("files/x.txt")

    assert data == b"hello"
    assert metadata is client.files.get_metadata.return_value
    client.files.get_metadata.assert_awaited_once_with("files/x.txt")
    client.files.download.assert_awaited_once_with("files/x.txt")


@pytest.mark.asyncio
async def test_fetch_rejects_oversize_via_metadata():
    client = _make_mock_dial_client(content_length=11 * 1024 * 1024)
    downloader = _make_downloader(dial_client=client)

    with pytest.raises(ValueError, match="exceeds the limit"):
        await downloader.fetch("files/big.bin")

    client.files.download.assert_not_called()


@pytest.mark.asyncio
async def test_fetch_uses_resolver_value_for_limit():
    client = _make_mock_dial_client(content_length=2048)
    downloader = _make_downloader(
        dial_client=client,
        size_limit_resolver=_make_resolver(size_limit=1024),
    )

    with pytest.raises(ValueError, match="exceeds the limit of 1024"):
        await downloader.fetch("files/medium.bin")


@pytest.mark.asyncio
async def test_fetch_project_file_goes_to_v2():
    client = _make_mock_dial_client()
    project_files = MagicMock(spec=ProjectFilesClient)
    project_files.stream = project_stream(b"project", etag="file-etag")
    downloader = _make_downloader(
        dial_client=client, project_files=project_files, project=ProjectContext(url="projects/b/p")
    )

    data, metadata = await downloader.fetch("projects/b/p/files/context/a.csv")

    assert data == b"project"
    assert metadata.etag == "file-etag"
    assert metadata.content_length == len(b"project")
    project_files.stream.assert_called_once_with("projects/b/p/files/context/a.csv")
    client.files.get_metadata.assert_not_awaited()
    client.files.download.assert_not_awaited()


@pytest.mark.asyncio
async def test_fetch_project_file_over_the_limit_is_rejected():
    project_files = MagicMock(spec=ProjectFilesClient)
    project_files.stream = project_stream(b"x" * 11)
    downloader = _make_downloader(
        size_limit_resolver=_make_resolver(10),
        project_files=project_files,
        project=ProjectContext(url="projects/b/p"),
    )

    with pytest.raises(FileTooLargeError, match="exceeds the limit"):
        await downloader.fetch("projects/b/p/files/context/a.csv")


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


@pytest.mark.parametrize("project", [None, ProjectContext(url="projects/b/other")])
@pytest.mark.asyncio
async def test_project_url_outside_the_requests_project_stays_on_v1(project):
    client = _make_mock_dial_client()
    project_files = MagicMock(spec=ProjectFilesClient)
    downloader = _make_downloader(dial_client=client, project_files=project_files, project=project)

    await downloader.fetch("projects/b/p/files/context/a.csv")

    project_files.stream.assert_not_called()
    client.files.download.assert_awaited_once_with("projects/b/p/files/context/a.csv")
