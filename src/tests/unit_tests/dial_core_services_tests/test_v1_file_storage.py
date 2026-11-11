from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aidial_client import AsyncDial, DialException, ResourceNotFoundError

from quickapp.dial_core_services.exceptions import FileTooLargeError
from quickapp.dial_core_services.storage._v1_file_storage import V1FileStorage
from quickapp.dial_core_services.storage.file_storage import FolderEntry
from quickapp.shared.config_resolvers.file_loading_size_limit_resolver import (
    FileLoadingSizeLimitResolver,
)

FILE = "files/b/notes/a.md"
FOLDER = "files/b/notes/"


def _make_client() -> MagicMock:
    client = MagicMock(spec=AsyncDial)
    client.files = MagicMock()
    client.metadata = MagicMock()
    return client


def _make_storage(client: MagicMock, size_limit: int = 100) -> V1FileStorage:
    resolver = MagicMock(spec=FileLoadingSizeLimitResolver)
    resolver.resolve.return_value = size_limit
    return V1FileStorage(client, resolver)


def _download_response(data: bytes) -> MagicMock:
    response = MagicMock()
    response.aget_content = AsyncMock(return_value=data)
    return response


class TestDownload:
    @pytest.mark.asyncio
    async def test_returns_the_bytes_and_the_metadata(self):
        client = _make_client()
        metadata = SimpleNamespace(content_length=5)
        client.files.get_metadata = AsyncMock(return_value=metadata)
        client.files.download = AsyncMock(return_value=_download_response(b"hello"))

        data, returned = await _make_storage(client).download(FILE)

        assert (data, returned) == (b"hello", metadata)
        client.files.download.assert_awaited_once_with(FILE)

    @pytest.mark.asyncio
    async def test_a_404_from_the_metadata_call_becomes_resource_not_found(self):
        client = _make_client()
        client.files.get_metadata = AsyncMock(
            side_effect=DialException(message="missing", status_code=404)
        )

        with pytest.raises(ResourceNotFoundError):
            await _make_storage(client).download(FILE)

    @pytest.mark.asyncio
    async def test_other_errors_propagate_unchanged(self):
        client = _make_client()
        error = DialException(message="denied", status_code=403)
        client.files.get_metadata = AsyncMock(side_effect=error)

        with pytest.raises(DialException) as excinfo:
            await _make_storage(client).download(FILE)

        assert excinfo.value is error

    @pytest.mark.asyncio
    async def test_over_the_limit_is_rejected_before_the_body(self):
        client = _make_client()
        client.files.get_metadata = AsyncMock(return_value=SimpleNamespace(content_length=11))
        client.files.download = AsyncMock()

        with pytest.raises(FileTooLargeError):
            await _make_storage(client, size_limit=10).download(FILE)

        client.files.download.assert_not_awaited()


class TestListLevel:
    @pytest.mark.asyncio
    async def test_items_become_entries_with_folder_slash_and_size(self):
        client = _make_client()
        client.metadata.get = AsyncMock(
            return_value=SimpleNamespace(
                node_type="FOLDER",
                items=[
                    SimpleNamespace(url=f"{FOLDER}a.md", node_type="ITEM", content_length=3),
                    SimpleNamespace(url=f"{FOLDER}sub", node_type="FOLDER", content_length=None),
                    SimpleNamespace(url=f"{FOLDER}done/", node_type="FOLDER", content_length=None),
                ],
            )
        )

        entries = await _make_storage(client).list_level(FOLDER)

        assert entries == [
            FolderEntry(url=f"{FOLDER}a.md", is_folder=False, size=3),
            FolderEntry(url=f"{FOLDER}sub/", is_folder=True, size=None),
            FolderEntry(url=f"{FOLDER}done/", is_folder=True, size=None),
        ]
        # The URL is passed verbatim, so the trailing slash Core needs is kept.
        client.metadata.get.assert_awaited_once_with("files", FOLDER)

    @pytest.mark.asyncio
    async def test_an_empty_folder_lists_as_empty(self):
        client = _make_client()
        client.metadata.get = AsyncMock(
            return_value=SimpleNamespace(node_type="FOLDER", items=None)
        )

        assert await _make_storage(client).list_level(FOLDER) == []

    @pytest.mark.asyncio
    async def test_a_404_becomes_resource_not_found(self):
        client = _make_client()
        client.metadata.get = AsyncMock(
            side_effect=DialException(message="missing", status_code=404)
        )

        with pytest.raises(ResourceNotFoundError):
            await _make_storage(client).list_level(FOLDER)

    @pytest.mark.asyncio
    async def test_a_file_is_not_a_folder(self):
        client = _make_client()
        client.metadata.get = AsyncMock(return_value=SimpleNamespace(node_type="ITEM", items=None))

        with pytest.raises(ValueError, match="not a folder"):
            await _make_storage(client).list_level(FOLDER)


class TestUpload:
    @pytest.mark.asyncio
    async def test_preconditions_reach_the_client_and_core_metadata_is_returned(self):
        client = _make_client()
        metadata = SimpleNamespace(url="files/b/notes/a.md")
        client.files.upload = AsyncMock(return_value=metadata)

        uploaded = await _make_storage(client).upload(
            FILE, b"data", "text/markdown", if_none_match="*", if_match="etag-1"
        )

        assert uploaded is metadata
        client.files.upload.assert_awaited_once_with(
            url=FILE,
            file=("a.md", b"data", "text/markdown"),
            etag_if_none_match="*",
            etag_if_match="etag-1",
        )

    @pytest.mark.asyncio
    async def test_without_preconditions_none_is_passed(self):
        client = _make_client()
        client.files.upload = AsyncMock(return_value=SimpleNamespace(url=FILE))

        await _make_storage(client).upload(FILE, b"data", "text/plain")

        call = client.files.upload.await_args
        assert call is not None
        kwargs = call.kwargs
        assert (kwargs["etag_if_none_match"], kwargs["etag_if_match"]) == (None, None)


class TestDeleteCopyMove:
    @pytest.mark.asyncio
    async def test_delete_delegates(self):
        client = _make_client()
        client.files.delete = AsyncMock()

        await _make_storage(client).delete(FILE)

        client.files.delete.assert_awaited_once_with(FILE)

    @pytest.mark.parametrize("overwrite", [True, False])
    @pytest.mark.asyncio
    async def test_copy_delegates_unchanged(self, overwrite: bool):
        client = _make_client()
        client.files.copy_to = AsyncMock()

        await _make_storage(client).copy(FILE, "files/b/b.md", overwrite)

        client.files.copy_to.assert_awaited_once_with(
            source=FILE, destination="files/b/b.md", overwrite=overwrite
        )

    @pytest.mark.parametrize("overwrite", [True, False])
    @pytest.mark.asyncio
    async def test_move_delegates_unchanged(self, overwrite: bool):
        client = _make_client()
        client.files.move_to = AsyncMock()

        await _make_storage(client).move(FILE, "files/b/b.md", overwrite)

        client.files.move_to.assert_awaited_once_with(
            source=FILE, destination="files/b/b.md", overwrite=overwrite
        )
