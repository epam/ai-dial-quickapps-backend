from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from quickapp.common.state_holder import StateHolder
from quickapp.dial_core_services._file_service_settings import FileServiceSettings
from quickapp.dial_core_services.dial_file_service import DialFileService


def _make_mock_dial_client(
    content_length: int = 100,
    file_content: bytes = b"file content",
) -> MagicMock:
    mock_metadata = MagicMock()
    mock_metadata.content_length = content_length

    mock_download_result = MagicMock()
    mock_download_result.aget_content = AsyncMock(return_value=file_content)

    mock_files = MagicMock()
    mock_files.get_metadata = AsyncMock(return_value=mock_metadata)
    mock_files.download = AsyncMock(return_value=mock_download_result)

    mock_resource_permissions = MagicMock()
    mock_resource_permissions.grant = AsyncMock(return_value=None)

    mock_dial_client = MagicMock()
    mock_dial_client.files = mock_files
    mock_dial_client.resource_permissions = mock_resource_permissions
    return mock_dial_client


def _make_app_config(max_file_download_bytes: int | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        tool_defaults=SimpleNamespace(max_file_download_bytes=max_file_download_bytes)
    )


def _make_service(
    dial_client: MagicMock | None = None,
    state_holder: StateHolder | None = None,
    app_config: SimpleNamespace | None = None,
    settings: FileServiceSettings | None = None,
) -> DialFileService:
    return DialFileService(
        dial_client=dial_client or _make_mock_dial_client(),
        state_holder=state_holder or StateHolder(),
        app_config=app_config or _make_app_config(),  # type: ignore[arg-type]
        settings=settings or FileServiceSettings(),
    )


class TestDownloadFile:
    @pytest.mark.asyncio
    async def test_cache_miss_downloads_and_stores(self):
        file_bytes = b"file content"
        mock_dial_client = _make_mock_dial_client(content_length=100, file_content=file_bytes)
        svc = _make_service(dial_client=mock_dial_client)

        result = await svc.download_file("files/test.txt")

        assert result == file_bytes
        mock_dial_client.files.get_metadata.assert_awaited_once_with("files/test.txt")
        mock_dial_client.files.download.assert_awaited_once_with("files/test.txt")

    @pytest.mark.asyncio
    async def test_cache_hit_returns_from_state(self):
        holder = StateHolder()
        holder.store_file_data("files/cached.txt", b"cached content")
        mock_dial_client = _make_mock_dial_client()
        svc = _make_service(dial_client=mock_dial_client, state_holder=holder)

        result = await svc.download_file("files/cached.txt")

        assert result == b"cached content"
        mock_dial_client.files.get_metadata.assert_not_called()
        mock_dial_client.files.download.assert_not_called()

    @pytest.mark.asyncio
    async def test_file_exceeds_size_limit_raises_error(self):
        mock_dial_client = _make_mock_dial_client(content_length=11 * 1024 * 1024)
        svc = _make_service(dial_client=mock_dial_client)

        with pytest.raises(ValueError, match="exceeds the limit"):
            await svc.download_file("files/huge.bin")

        mock_dial_client.files.download.assert_not_called()

    @pytest.mark.asyncio
    async def test_app_override_limit_takes_precedence(self):
        mock_dial_client = _make_mock_dial_client(content_length=2048)
        svc = _make_service(
            dial_client=mock_dial_client,
            app_config=_make_app_config(max_file_download_bytes=1024),
        )

        with pytest.raises(ValueError, match="exceeds the limit of 1024"):
            await svc.download_file("files/medium.bin")

    @pytest.mark.asyncio
    async def test_env_default_used_when_app_override_unset(self, monkeypatch):
        monkeypatch.setenv("DIAL_FILE_MAX_DOWNLOAD_BYTES", "100")
        mock_dial_client = _make_mock_dial_client(content_length=200)
        svc = _make_service(
            dial_client=mock_dial_client,
            settings=FileServiceSettings(),
            app_config=_make_app_config(max_file_download_bytes=None),
        )

        with pytest.raises(ValueError, match="exceeds the limit of 100"):
            await svc.download_file("files/small.bin")


class TestGrantPermissions:
    @pytest.mark.asyncio
    async def test_grant_permissions_calls_client(self):
        mock_dial_client = _make_mock_dial_client()
        svc = _make_service(dial_client=mock_dial_client)

        await svc.grant_permissions_to_files(["files/a.txt", "files/b.txt"], "my-toolset")

        mock_dial_client.resource_permissions.grant.assert_awaited_once_with(
            resources=["files/a.txt", "files/b.txt"],
            receiver="my-toolset",
        )
