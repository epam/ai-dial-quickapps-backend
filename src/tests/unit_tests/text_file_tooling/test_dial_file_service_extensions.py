from unittest.mock import AsyncMock, MagicMock

import pytest
from aidial_client._exception import EtagMismatchError

from quickapp.common.state_holder import StateHolder
from quickapp.dial_core_services.dial_file_service import DialFileService


def _make_mock_dial_client(
    content_length: int = 100,
    file_content: bytes = b"hello",
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
    mock_files.get_metadata = AsyncMock(return_value=mock_metadata)
    mock_files.download = AsyncMock(return_value=mock_download_result)
    mock_files.upload = AsyncMock(return_value=mock_metadata)

    mock_bucket = MagicMock()
    mock_bucket.appdata = None
    mock_bucket.bucket = "mybucket"
    mock_dial_client = MagicMock()
    mock_dial_client.files = mock_files
    mock_dial_client.bucket = MagicMock()
    mock_dial_client.bucket.get_raw = AsyncMock(return_value=mock_bucket)
    return mock_dial_client


def _make_service(
    dial_client: MagicMock | None = None,
    state_holder: StateHolder | None = None,
) -> DialFileService:
    return DialFileService(
        dial_client=dial_client or _make_mock_dial_client(),
        state_holder=state_holder or StateHolder(),
    )


class TestUploadText:
    @pytest.mark.asyncio
    async def test_create_only_passes_if_none_match(self):
        mock_client = _make_mock_dial_client(upload_url="files/b/generated-files/f.txt")
        svc = _make_service(dial_client=mock_client)

        result = await svc.upload_text(
            url="files/b/generated-files/f.txt",
            content="hello",
            if_none_match="*",
        )

        assert result == "files/b/generated-files/f.txt"
        mock_client.files.upload.assert_awaited_once()
        call_kwargs = mock_client.files.upload.call_args
        assert call_kwargs.kwargs.get("etag_if_none_match") == "*"
        assert call_kwargs.kwargs.get("etag_if_match") is None

    @pytest.mark.asyncio
    async def test_update_passes_if_match(self):
        mock_client = _make_mock_dial_client(upload_url="files/b/generated-files/f.txt")
        svc = _make_service(dial_client=mock_client)

        await svc.upload_text(
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
            await svc.upload_text(url="files/b/f.txt", content="x", if_none_match="*")

    @pytest.mark.asyncio
    async def test_returns_confirmed_url(self):
        mock_client = _make_mock_dial_client(upload_url="files/b/generated-files/notes.md")
        svc = _make_service(dial_client=mock_client)

        result = await svc.upload_text(
            url="files/b/generated-files/notes.md",
            content="# Notes\n",
        )
        assert result == "files/b/generated-files/notes.md"


class TestDownloadFileWithEtag:
    @pytest.mark.asyncio
    async def test_returns_bytes_and_etag(self):
        file_bytes = b"content here"
        mock_client = _make_mock_dial_client(file_content=file_bytes, etag="rev1")
        svc = _make_service(dial_client=mock_client)

        data, etag = await svc.download_file_with_etag("files/b/f.txt")

        assert data == file_bytes
        assert etag == "rev1"

    @pytest.mark.asyncio
    async def test_uses_cache_for_bytes(self):
        holder = StateHolder()
        holder.store_file_data("files/b/cached.txt", b"cached")
        mock_client = _make_mock_dial_client(etag="e1")
        svc = _make_service(dial_client=mock_client, state_holder=holder)

        data, etag = await svc.download_file_with_etag("files/b/cached.txt")

        assert data == b"cached"
        assert etag == "e1"
        mock_client.files.download.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_etag_none_returns_empty_string(self):
        mock_client = _make_mock_dial_client(etag=None)
        svc = _make_service(dial_client=mock_client)

        _, etag = await svc.download_file_with_etag("files/b/f.txt")
        assert etag == ""


class TestInvalidateCache:
    @pytest.mark.asyncio
    async def test_subsequent_download_hits_network_after_invalidation(self):
        file_bytes_v1 = b"version1"
        file_bytes_v2 = b"version2"
        mock_client = _make_mock_dial_client(file_content=file_bytes_v1)
        svc = _make_service(dial_client=mock_client)

        first = await svc.download_file("files/b/f.txt")
        assert first == file_bytes_v1

        # Now invalidate and change what the mock returns
        svc.invalidate_cache("files/b/f.txt")
        mock_client.files.download.return_value.aget_content = AsyncMock(return_value=file_bytes_v2)
        mock_client.files.get_metadata.return_value.content_length = 100

        second = await svc.download_file("files/b/f.txt")
        assert second == file_bytes_v2


class TestTextFileToolsConfig:
    def test_default_enabled_tools_is_all(self):
        from quickapp.config.text_file_tools import TextFileToolsConfig

        cfg = TextFileToolsConfig()
        assert cfg.enabled_tools == "all"

    def test_list_of_tools_accepted(self):
        from quickapp.config.text_file_tools import TextFileToolsConfig

        cfg = TextFileToolsConfig(
            enabled_tools=["internal_text_file_read_lines", "internal_text_file_search"]
        )
        assert cfg.enabled_tools == ["internal_text_file_read_lines", "internal_text_file_search"]
