from unittest.mock import AsyncMock, MagicMock

import pytest
from aidial_client._exception import DialException, EtagMismatchError, ResourceNotFoundError

from quickapp.common.state_holder import StateHolder
from quickapp.dial_core_services.dial_file_service import DialFileService
from quickapp.shared.config_resolvers.file_loading_size_limit_resolver import (
    FileLoadingSizeLimitResolver,
)

DEFAULT_LIMIT = 10 * 1024 * 1024


def _make_mock_dial_client(
    content_length: int = 100,
    file_content: bytes = b"file content",
    upload_url: str = "files/bucket/generated-files/out.txt",
    etag: str | None = "abc123",
) -> MagicMock:
    mock_metadata = MagicMock()
    mock_metadata.content_length = content_length
    mock_metadata.etag = etag
    mock_metadata.url = upload_url

    mock_download_result = MagicMock()
    mock_download_result.aget_content = AsyncMock(return_value=file_content)

    mock_files = MagicMock()
    mock_files.download = AsyncMock(return_value=mock_download_result)
    mock_files.upload = AsyncMock(return_value=mock_metadata)

    # The service fetches file/folder metadata via metadata.get (not files.get_metadata).
    mock_metadata_resource = MagicMock()
    mock_metadata_resource.get = AsyncMock(return_value=mock_metadata)

    mock_bucket = MagicMock()
    mock_bucket.appdata = None
    mock_bucket.bucket = "mybucket"

    mock_resource_permissions = MagicMock()
    mock_resource_permissions.grant = AsyncMock(return_value=None)

    mock_dial_client = MagicMock()
    mock_dial_client.files = mock_files
    mock_dial_client.metadata = mock_metadata_resource
    mock_dial_client.resource_permissions = mock_resource_permissions
    mock_dial_client.bucket = MagicMock()
    mock_dial_client.bucket.get_raw = AsyncMock(return_value=mock_bucket)
    return mock_dial_client


def _make_resolver(size_limit: int = DEFAULT_LIMIT) -> MagicMock:
    resolver = MagicMock(spec=FileLoadingSizeLimitResolver)
    resolver.resolve.return_value = size_limit
    return resolver


def _make_service(
    dial_client: MagicMock | None = None,
    state_holder: StateHolder | None = None,
    size_limit_resolver: MagicMock | None = None,
) -> DialFileService:
    return DialFileService(
        dial_client=dial_client or _make_mock_dial_client(),
        state_holder=state_holder or StateHolder(),
        size_limit_resolver=size_limit_resolver or _make_resolver(),
    )


class TestDownloadFile:
    @pytest.mark.asyncio
    async def test_cache_miss_downloads_and_stores(self):
        file_bytes = b"file content"
        mock_dial_client = _make_mock_dial_client(content_length=100, file_content=file_bytes)
        svc = _make_service(dial_client=mock_dial_client)

        data, metadata = await svc.download_file("files/test.txt")

        assert data == file_bytes
        assert metadata is not None
        mock_dial_client.metadata.get.assert_awaited_once_with("files", "files/test.txt")
        mock_dial_client.files.download.assert_awaited_once_with("files/test.txt")

    @pytest.mark.asyncio
    async def test_cache_hit_returns_from_state(self):
        holder = StateHolder()
        stored_metadata = MagicMock()
        holder.store_file_data("files/cached.txt", b"cached content", stored_metadata)
        mock_dial_client = _make_mock_dial_client()
        svc = _make_service(dial_client=mock_dial_client, state_holder=holder)

        data, metadata = await svc.download_file("files/cached.txt")

        assert data == b"cached content"
        assert metadata is stored_metadata
        mock_dial_client.metadata.get.assert_not_called()
        mock_dial_client.files.download.assert_not_called()

    @pytest.mark.asyncio
    async def test_file_exceeds_size_limit_raises_error(self):
        mock_dial_client = _make_mock_dial_client(content_length=11 * 1024 * 1024)
        svc = _make_service(dial_client=mock_dial_client)

        with pytest.raises(ValueError, match="exceeds the limit"):
            await svc.download_file("files/huge.bin")

        mock_dial_client.files.download.assert_not_called()

    @pytest.mark.asyncio
    async def test_resolver_value_drives_limit(self):
        mock_dial_client = _make_mock_dial_client(content_length=2048)
        svc = _make_service(
            dial_client=mock_dial_client,
            size_limit_resolver=_make_resolver(size_limit=1024),
        )

        with pytest.raises(ValueError, match="exceeds the limit of 1024"):
            await svc.download_file("files/medium.bin")

    @pytest.mark.asyncio
    async def test_base_dialexception_404_raises_resource_not_found(self):
        # metadata.get has no on_http_error handler, so a real 404 arrives as a base
        # DialException. It must be normalized to ResourceNotFoundError.
        mock_client = _make_mock_dial_client()
        mock_client.metadata.get = AsyncMock(side_effect=DialException(message="", status_code=404))
        svc = _make_service(dial_client=mock_client)

        with pytest.raises(ResourceNotFoundError):
            await svc.download_file("files/missing.txt")


class TestWriteFile:
    @pytest.mark.asyncio
    async def test_create_only_passes_if_none_match(self):
        mock_client = _make_mock_dial_client(upload_url="files/b/generated-files/f.txt")
        svc = _make_service(dial_client=mock_client)

        result = await svc.write_file(
            url="files/b/generated-files/f.txt",
            content="hello",
        )

        assert result == "files/b/generated-files/f.txt"
        mock_client.files.upload.assert_awaited_once()
        call_kwargs = mock_client.files.upload.call_args
        assert call_kwargs.kwargs.get("etag_if_none_match") == "*"
        assert call_kwargs.kwargs.get("etag_if_match") is None

    @pytest.mark.asyncio
    async def test_if_match_passes_if_match(self):
        mock_client = _make_mock_dial_client(upload_url="files/b/generated-files/f.txt")
        svc = _make_service(dial_client=mock_client)

        await svc.write_file(
            url="files/b/generated-files/f.txt",
            content="new content",
            if_match="etag-xyz",
        )

        call_kwargs = mock_client.files.upload.call_args
        assert call_kwargs.kwargs.get("etag_if_match") == "etag-xyz"
        assert call_kwargs.kwargs.get("etag_if_none_match") is None

    @pytest.mark.asyncio
    async def test_propagates_412_as_etag_mismatch_error(self):
        mock_client = _make_mock_dial_client()
        mock_client.files.upload = AsyncMock(side_effect=EtagMismatchError(message="412"))
        svc = _make_service(dial_client=mock_client)

        with pytest.raises(EtagMismatchError):
            await svc.write_file(url="files/b/f.txt", content="x")

    @pytest.mark.asyncio
    async def test_returns_confirmed_url(self):
        mock_client = _make_mock_dial_client(upload_url="files/b/generated-files/notes.md")
        svc = _make_service(dial_client=mock_client)

        result = await svc.write_file(
            url="files/b/generated-files/notes.md",
            content="# Notes\n",
        )
        assert result == "files/b/generated-files/notes.md"

    @pytest.mark.asyncio
    async def test_overwrite_uploads_unconditionally(self):
        # overwrite=True is a deliberate create-or-replace: upload with no ETag
        # conditions and no metadata round-trip, so a not-yet-existing file is
        # simply created rather than erroring out.
        mock_client = _make_mock_dial_client(upload_url="files/b/new.txt")
        svc = _make_service(dial_client=mock_client)

        result = await svc.write_file(url="files/b/new.txt", content="hello", overwrite=True)

        assert result == "files/b/new.txt"
        mock_client.metadata.get.assert_not_called()
        mock_client.files.upload.assert_awaited_once()
        call_kwargs = mock_client.files.upload.call_args.kwargs
        assert call_kwargs.get("etag_if_none_match") is None
        assert call_kwargs.get("etag_if_match") is None


class TestListFolder:
    @pytest.mark.asyncio
    async def test_base_dialexception_404_raises_resource_not_found(self):
        # list_folder calls metadata.get directly; a missing folder 404s as a base
        # DialException, which must be normalized so callers can treat it as not-found.
        mock_client = _make_mock_dial_client()
        mock_client.metadata.get = AsyncMock(side_effect=DialException(message="", status_code=404))
        svc = _make_service(dial_client=mock_client)

        with pytest.raises(ResourceNotFoundError):
            await svc.list_folder("files/appbucket/")


class TestInvalidateCache:
    @pytest.mark.asyncio
    async def test_subsequent_download_hits_network_after_invalidation(self):
        file_bytes_v1 = b"version1"
        file_bytes_v2 = b"version2"
        mock_client = _make_mock_dial_client(file_content=file_bytes_v1)
        svc = _make_service(dial_client=mock_client)

        first, _ = await svc.download_file("files/b/f.txt")
        assert first == file_bytes_v1

        # Now invalidate and change what the mock returns
        svc.invalidate_cache("files/b/f.txt")
        mock_client.files.download.return_value.aget_content = AsyncMock(return_value=file_bytes_v2)
        mock_client.metadata.get.return_value.content_length = 100

        second, _ = await svc.download_file("files/b/f.txt")
        assert second == file_bytes_v2


class TestGrantPermissions:
    @pytest.mark.asyncio
    async def test_grant_permissions_calls_client(self):
        client = _make_mock_dial_client()
        svc = _make_service(dial_client=client)

        await svc.grant_permissions_to_files(["files/a.txt", "files/b.txt"], "my-toolset")

        client.resource_permissions.grant.assert_awaited_once_with(
            resources=["files/a.txt", "files/b.txt"],
            receiver="my-toolset",
        )

    @pytest.mark.asyncio
    async def test_grant_permissions_propagates_failure(self):
        client = _make_mock_dial_client()
        client.resource_permissions.grant.side_effect = RuntimeError("boom")
        svc = _make_service(dial_client=client)

        with pytest.raises(RuntimeError, match="boom"):
            await svc.grant_permissions_to_files(["files/x.txt"], "toolset")
