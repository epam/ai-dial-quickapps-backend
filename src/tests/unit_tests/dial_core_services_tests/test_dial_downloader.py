from unittest.mock import AsyncMock, MagicMock

import pytest

from quickapp.common.project_context import ProjectContext
from quickapp.dial_core_services._project_files import ProjectFilesClient
from quickapp.dial_core_services.dial_downloader import DialDownloader
from quickapp.shared.config_resolvers.file_loading_size_limit_resolver import (
    FileLoadingSizeLimitResolver,
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
    metadata = MagicMock()
    project_files.download = AsyncMock(return_value=(b"project", metadata))
    downloader = _make_downloader(
        dial_client=client, project_files=project_files, project=ProjectContext(url="projects/b/p")
    )

    data, result_metadata = await downloader.fetch("projects/b/p/files/context/a.csv")

    assert data == b"project"
    assert result_metadata is metadata
    client.files.get_metadata.assert_not_awaited()
    client.files.download.assert_not_awaited()


@pytest.mark.asyncio
async def test_fetch_project_file_over_the_limit_is_rejected():
    project_files = MagicMock(spec=ProjectFilesClient)
    project_files.download = AsyncMock(return_value=(b"x" * 11, MagicMock()))
    downloader = _make_downloader(
        size_limit_resolver=_make_resolver(10),
        project_files=project_files,
        project=ProjectContext(url="projects/b/p"),
    )

    with pytest.raises(ValueError, match="exceeds the limit"):
        await downloader.fetch("projects/b/p/files/context/a.csv")


@pytest.mark.parametrize("project", [None, ProjectContext(url="projects/b/other")])
@pytest.mark.asyncio
async def test_project_url_outside_the_requests_project_stays_on_v1(project):
    client = _make_mock_dial_client()
    project_files = MagicMock(spec=ProjectFilesClient)
    downloader = _make_downloader(dial_client=client, project_files=project_files, project=project)

    await downloader.fetch("projects/b/p/files/context/a.csv")

    project_files.download.assert_not_called()
    client.files.download.assert_awaited_once_with("projects/b/p/files/context/a.csv")
