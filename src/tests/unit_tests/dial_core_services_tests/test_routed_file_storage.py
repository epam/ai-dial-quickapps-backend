from unittest.mock import AsyncMock, MagicMock

import pytest
from aidial_client._exception import DialException

from quickapp.common.project_context import ProjectContext
from quickapp.dial_core_services.exceptions import (
    PartialMoveException,
    ProjectFileOperationException,
    SameSourceAndDestinationException,
)
from quickapp.dial_core_services.storage._routed_file_storage import RoutedFileStorage
from quickapp.dial_core_services.storage._transfer import copy_via_download
from quickapp.dial_core_services.storage.file_storage import FileStorage

PROJECT = ProjectContext(url="projects/b/p")
PROJECT_FILE = "projects/b/p/files/artifacts/notes.md"
V1_FILE = "files/bucket/a.txt"


def _make_storage(data: bytes = b"data", content_type: str = "text/plain") -> MagicMock:
    storage = MagicMock(spec=FileStorage)
    metadata = MagicMock()
    metadata.content_type = content_type
    storage.download = AsyncMock(return_value=(data, metadata))
    storage.upload = AsyncMock(return_value="uploaded")
    storage.delete = AsyncMock()
    storage.list_level = AsyncMock(return_value=[])
    storage.copy = AsyncMock()
    storage.move = AsyncMock()
    return storage


def _make_router(v1: MagicMock, project: MagicMock, max_bytes: int = 100) -> RoutedFileStorage:
    return RoutedFileStorage(v1, project, PROJECT, max_bytes)


class TestSingleUrlRouting:
    @pytest.mark.parametrize(
        "url, goes_to_project",
        [
            (PROJECT_FILE, True),
            ("projects/b/p/files/artifacts/", True),
            (V1_FILE, False),
            ("projects/b/other/files/x.md", False),
            ("projects/b/p/files/../../other/files/x.md", False),
        ],
    )
    @pytest.mark.asyncio
    async def test_each_operation_goes_to_the_storage_that_owns_the_url(self, url, goes_to_project):
        v1, project = _make_storage(), _make_storage()
        router = _make_router(v1, project)

        await router.download(url, 10)
        await router.upload(url, b"x", "text/plain", if_match="e")
        await router.delete(url)
        await router.list_level(url)

        chosen, other = (project, v1) if goes_to_project else (v1, project)
        chosen.download.assert_awaited_once_with(url, 10)
        chosen.upload.assert_awaited_once_with(
            url, b"x", "text/plain", if_none_match=None, if_match="e"
        )
        chosen.delete.assert_awaited_once_with(url)
        chosen.list_level.assert_awaited_once_with(url)
        for method in (other.download, other.upload, other.delete, other.list_level):
            method.assert_not_awaited()


class TestCopyAndMove:
    @pytest.mark.parametrize("operation", ["copy", "move"])
    @pytest.mark.parametrize(
        "source, destination, owner",
        [
            (V1_FILE, "files/bucket/b.txt", "v1"),
            (PROJECT_FILE, "projects/b/p/files/artifacts/b.md", "project"),
        ],
    )
    @pytest.mark.asyncio
    async def test_within_one_storage_uses_its_own(self, operation, source, destination, owner):
        v1, project = _make_storage(), _make_storage()
        storages = {"v1": v1, "project": project}

        await getattr(_make_router(v1, project), operation)(source, destination, True)

        getattr(storages[owner], operation).assert_awaited_once_with(source, destination, True)
        for storage in (v1, project):
            storage.download.assert_not_awaited()
            storage.upload.assert_not_awaited()

    @pytest.mark.parametrize("overwrite, if_none_match", [(True, None), (False, "*")])
    @pytest.mark.asyncio
    async def test_copy_between_storages_downloads_then_uploads(self, overwrite, if_none_match):
        v1, project = _make_storage(data=b"v1 data", content_type="text/csv"), _make_storage()

        await _make_router(v1, project, max_bytes=50).copy(V1_FILE, PROJECT_FILE, overwrite)

        v1.download.assert_awaited_once_with(V1_FILE, 50)
        project.upload.assert_awaited_once_with(
            PROJECT_FILE, b"v1 data", "text/csv", if_none_match=if_none_match
        )
        v1.copy.assert_not_awaited()
        v1.delete.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_move_between_storages_deletes_the_source(self):
        v1, project = _make_storage(), _make_storage()

        await _make_router(v1, project).move(PROJECT_FILE, V1_FILE, True)

        v1.upload.assert_awaited_once()
        project.delete.assert_awaited_once_with(PROJECT_FILE)

    @pytest.mark.asyncio
    async def test_failed_delete_after_the_copy_is_a_partial_move(self):
        v1, project = _make_storage(), _make_storage()
        v1.delete = AsyncMock(side_effect=DialException(message="boom", status_code=500))

        with pytest.raises(PartialMoveException):
            await _make_router(v1, project).move(V1_FILE, PROJECT_FILE, True)
        project.upload.assert_awaited_once()

    @pytest.mark.parametrize("operation", ["copy", "move"])
    @pytest.mark.asyncio
    async def test_a_folder_between_storages_is_refused(self, operation):
        v1, project = _make_storage(), _make_storage()

        with pytest.raises(ProjectFileOperationException, match="folders"):
            await getattr(_make_router(v1, project), operation)(
                "files/bucket/folder/", "projects/b/p/files/artifacts/folder/", True
            )
        v1.download.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_the_same_file_spelled_two_ways_is_refused_before_any_io(self):
        storage = _make_storage()

        with pytest.raises(SameSourceAndDestinationException):
            await copy_via_download(
                storage,
                "projects/b/p/files/artifacts/My Notes.md",
                storage,
                "projects/b/p/files/artifacts/My%20Notes.md",
                overwrite=True,
                max_bytes=100,
            )
        storage.download.assert_not_awaited()
        storage.upload.assert_not_awaited()
