"""``DialFileService`` with a project in the request, over the real storages (as DI wires them):
v2 dispatch and preconditions."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from aidial_client._exception import DialException, EtagMismatchError

from quickapp.common.project_context import ProjectContext
from quickapp.common.state_holder import StateHolder
from quickapp.dial_core_services._project_files import ProjectFilesClient, ProjectItem
from quickapp.dial_core_services.dial_file_service import DialFileService
from quickapp.dial_core_services.exceptions import (
    FileTooLargeError,
    PartialMoveException,
    ProjectFileOperationException,
    ProjectFileTooLargeException,
    SameSourceAndDestinationException,
)
from quickapp.dial_core_services.storage._project_file_storage import ProjectFileStorage
from quickapp.dial_core_services.storage._routed_file_storage import RoutedFileStorage
from quickapp.dial_core_services.storage._v1_file_storage import V1FileStorage
from quickapp.dial_core_services.storage.file_storage import FileStorage
from quickapp.shared.config_resolvers.file_loading_size_limit_resolver import (
    FileLoadingSizeLimitResolver,
)
from tests.unit_tests.dial_core_services_tests._project_stream import project_stream

PROJECT = ProjectContext(url="projects/b/p")
PROJECT_FILE = "projects/b/p/files/artifacts/notes.md"


def _make_dial_client(file_content: bytes = b"v1 data") -> MagicMock:
    metadata = MagicMock()
    metadata.content_length = len(file_content)
    metadata.content_type = "text/plain"
    metadata.url = "files/bucket/uploaded"
    download_result = MagicMock()
    download_result.aget_content = AsyncMock(return_value=file_content)

    client = MagicMock()
    client.metadata.get = AsyncMock(return_value=metadata)
    client.files.get_metadata = client.metadata.get
    client.files.download = AsyncMock(return_value=download_result)
    client.files.upload = AsyncMock(return_value=metadata)
    client.files.delete = AsyncMock()
    client.files.copy_to = AsyncMock()
    return client


def _make_project_files(
    data: bytes = b"project data",
    file_etag: str | None = "file-etag",
) -> MagicMock:
    project_files = MagicMock(spec=ProjectFilesClient)
    project_files.stream = project_stream(data, etag=file_etag)
    project_files.file_etag = AsyncMock(return_value=file_etag)
    project_files.put = AsyncMock(return_value=None)
    project_files.delete = AsyncMock(return_value=None)
    project_files.list = AsyncMock(return_value=[])
    return project_files


def _make_service(
    project_files: MagicMock,
    *,
    dial_client: MagicMock | None = None,
    project: ProjectContext | None = PROJECT,
    size_limit: int = 10 * 1024 * 1024,
) -> DialFileService:
    resolver = MagicMock(spec=FileLoadingSizeLimitResolver)
    resolver.resolve.return_value = size_limit
    dial_client = dial_client or _make_dial_client()
    v1 = V1FileStorage(dial_client)
    storage: FileStorage = (
        v1
        if project is None
        else RoutedFileStorage(v1, ProjectFileStorage(project_files, resolver), project, size_limit)
    )
    return DialFileService(
        dial_client=dial_client,
        storage=storage,
        state_holder=StateHolder(),
        size_limit_resolver=resolver,
    )


class TestDispatchGate:
    @pytest.mark.parametrize("project", [None, ProjectContext(url="projects/b/other")])
    @pytest.mark.asyncio
    async def test_projects_url_outside_the_requests_project_stays_on_v1(self, project):
        dial_client = _make_dial_client()
        project_files = _make_project_files()
        svc = _make_service(project_files, dial_client=dial_client, project=project)

        await svc.download_file(PROJECT_FILE)
        await svc.write_file(PROJECT_FILE, "x", overwrite=True)
        await svc.delete(PROJECT_FILE)

        project_files.stream.assert_not_called()
        project_files.put.assert_not_awaited()
        project_files.delete.assert_not_awaited()
        dial_client.files.download.assert_awaited_once()
        dial_client.files.upload.assert_awaited_once()
        dial_client.files.delete.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_files_urls_stay_on_v1_inside_a_project(self):
        dial_client = _make_dial_client()
        project_files = _make_project_files()
        svc = _make_service(project_files, dial_client=dial_client)

        await svc.download_file("files/bucket/a.txt")

        project_files.stream.assert_not_called()
        dial_client.files.download.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_unencoded_url_of_the_project_is_dispatched(self):
        project_files = _make_project_files()
        svc = _make_service(project_files, project=ProjectContext(url="projects/b/My Project"))

        await svc.download_file("projects/b/My Project/files/context/a.csv")

        project_files.stream.assert_called_once()


class TestReadsAndListing:
    @pytest.mark.asyncio
    async def test_download_goes_to_v2_and_is_cached(self):
        dial_client = _make_dial_client()
        project_files = _make_project_files()
        svc = _make_service(project_files, dial_client=dial_client)

        first = await svc.download_file(PROJECT_FILE)
        second = await svc.download_file(PROJECT_FILE)

        assert first[0] == second[0] == b"project data"
        project_files.stream.assert_called_once_with(PROJECT_FILE)
        dial_client.files.download.assert_not_awaited()
        dial_client.metadata.get.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_download_over_the_limit_is_rejected(self):
        svc = _make_service(_make_project_files(data=b"x" * 11), size_limit=10)

        with pytest.raises(FileTooLargeError, match="exceeds the limit"):
            await svc.download_file(PROJECT_FILE)

    @pytest.mark.asyncio
    async def test_delete_goes_to_v2(self):
        dial_client = _make_dial_client()
        project_files = _make_project_files()
        svc = _make_service(project_files, dial_client=dial_client)

        await svc.delete(PROJECT_FILE)

        project_files.delete.assert_awaited_once_with(PROJECT_FILE)
        dial_client.files.delete.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_list_folder_expands_to_max_depth(self):
        root = "projects/b/p/files/artifacts/"
        project_files = _make_project_files()
        project_files.list = AsyncMock(
            side_effect=[
                [
                    ProjectItem(url=f"{root}a.md", is_folder=False),
                    ProjectItem(url=f"{root}sub/", is_folder=True),
                ],
                [ProjectItem(url=f"{root}sub/b.md", is_folder=False)],
            ]
        )
        svc = _make_service(project_files)

        entries = await svc.list_folder(root, max_depth=2)

        assert [(e.url, e.is_folder, e.size) for e in entries] == [
            (f"{root}a.md", False, None),
            (f"{root}sub/", True, None),
            (f"{root}sub/b.md", False, None),
        ]


class TestWrites:
    @pytest.mark.asyncio
    async def test_unconditional_write_is_one_put_without_a_check(self):
        project_files = _make_project_files()
        project_files.put = AsyncMock(side_effect=EtagMismatchError(message="412"))
        svc = _make_service(project_files)

        with pytest.raises(EtagMismatchError):
            await svc.write_file(PROJECT_FILE, "hi", overwrite=True)

        project_files.put.assert_awaited_once_with(PROJECT_FILE, b"hi", "text/plain")
        project_files.file_etag.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_write_returns_the_url(self):
        svc = _make_service(_make_project_files())

        assert await svc.write_file(PROJECT_FILE, "hi", overwrite=True) == PROJECT_FILE

    @pytest.mark.asyncio
    async def test_create_only_checks_absence_then_puts_once(self):
        project_files = _make_project_files(file_etag=None)
        svc = _make_service(project_files)

        await svc.write_file(PROJECT_FILE, "hi")

        project_files.file_etag.assert_awaited_once_with(PROJECT_FILE)
        project_files.put.assert_awaited_once_with(PROJECT_FILE, b"hi", "text/plain")

    @pytest.mark.asyncio
    async def test_create_only_fails_when_the_file_exists(self):
        project_files = _make_project_files(file_etag="exists")
        svc = _make_service(project_files)

        with pytest.raises(EtagMismatchError, match="already exists"):
            await svc.write_file(PROJECT_FILE, "hi")
        with pytest.raises(EtagMismatchError, match="already exists"):
            await svc.write_bytes(PROJECT_FILE, b"hi")
        project_files.put.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_conditional_overwrite_compares_the_files_own_etag(self):
        project_files = _make_project_files(file_etag="current")
        svc = _make_service(project_files)

        with pytest.raises(EtagMismatchError):
            await svc.write_file(PROJECT_FILE, "hi", if_match="stale")
        project_files.put.assert_not_awaited()

        await svc.write_file(PROJECT_FILE, "hi", if_match="current")
        project_files.put.assert_awaited_once_with(PROJECT_FILE, b"hi", "text/plain")

    @pytest.mark.asyncio
    async def test_a_412_on_the_put_is_not_retried(self):
        project_files = _make_project_files(file_etag=None)
        project_files.put = AsyncMock(side_effect=EtagMismatchError(message="412"))
        svc = _make_service(project_files)

        with pytest.raises(EtagMismatchError):
            await svc.write_file(PROJECT_FILE, "hi")
        project_files.put.assert_awaited_once()


class TestCopyAndMove:
    @pytest.mark.asyncio
    async def test_copy_into_the_project_downloads_and_creates(self):
        dial_client = _make_dial_client(file_content=b"v1 data")
        project_files = _make_project_files(file_etag=None)
        svc = _make_service(project_files, dial_client=dial_client)

        await svc.copy("files/bucket/a.txt", PROJECT_FILE, overwrite=False)

        dial_client.files.copy_to.assert_not_awaited()
        project_files.put.assert_awaited_once()
        assert project_files.put.await_args.args[1] == b"v1 data"

    @pytest.mark.asyncio
    async def test_copy_without_overwrite_fails_when_the_destination_exists(self):
        svc = _make_service(_make_project_files(file_etag="exists"))

        with pytest.raises(EtagMismatchError, match="already exists"):
            await svc.copy(PROJECT_FILE, "projects/b/p/files/artifacts/copy.md", overwrite=False)

    @pytest.mark.asyncio
    async def test_move_within_the_project_deletes_the_source(self):
        project_files = _make_project_files()
        svc = _make_service(project_files)
        destination = "projects/b/p/files/artifacts/moved.md"

        await svc.move(PROJECT_FILE, destination, overwrite=True)

        project_files.put.assert_awaited_once_with(destination, b"project data", "text/markdown")
        project_files.delete.assert_awaited_once_with(PROJECT_FILE)

    @pytest.mark.asyncio
    async def test_failed_delete_after_the_copy_is_a_partial_move(self):
        project_files = _make_project_files()
        project_files.delete = AsyncMock(side_effect=DialException(message="boom", status_code=500))
        svc = _make_service(project_files)

        with pytest.raises(PartialMoveException, match="source still exists"):
            await svc.move(PROJECT_FILE, "projects/b/p/files/artifacts/moved.md", overwrite=True)
        project_files.put.assert_awaited_once()


class TestReviewFixes:
    @pytest.mark.parametrize(
        "source, destination",
        [
            ("projects/b/p/files/context/", "projects/b/p/files/artifacts/context/"),
            ("files/bucket/folder/", "projects/b/p/files/artifacts/folder/"),
        ],
    )
    @pytest.mark.parametrize("operation", ["copy", "move"])
    @pytest.mark.asyncio
    async def test_a_folder_source_is_refused_before_any_download(
        self, source, destination, operation
    ):
        dial_client = _make_dial_client()
        project_files = _make_project_files()
        svc = _make_service(project_files, dial_client=dial_client)

        with pytest.raises(ProjectFileOperationException, match="folders in a project"):
            await getattr(svc, operation)(source, destination, overwrite=True)
        project_files.stream.assert_not_called()
        dial_client.files.download.assert_not_awaited()
        project_files.put.assert_not_awaited()
        project_files.delete.assert_not_awaited()

    @pytest.mark.parametrize(
        "source, destination",
        [
            (PROJECT_FILE, PROJECT_FILE),
            (
                "projects/b/p/files/artifacts/My Notes.md",
                "projects/b/p/files/artifacts/My%20Notes.md",
            ),
        ],
    )
    @pytest.mark.parametrize("operation", ["copy", "move"])
    @pytest.mark.asyncio
    async def test_onto_itself_is_refused_without_writing_or_deleting(
        self, source, destination, operation
    ):
        project_files = _make_project_files()
        svc = _make_service(project_files)

        with pytest.raises(SameSourceAndDestinationException):
            await getattr(svc, operation)(source, destination, overwrite=True)
        project_files.stream.assert_not_called()
        project_files.put.assert_not_awaited()
        project_files.delete.assert_not_awaited()

    @pytest.mark.parametrize("operation", ["copy", "move"])
    @pytest.mark.asyncio
    async def test_copy_over_the_size_limit_is_a_clear_refusal(self, operation):
        project_files = _make_project_files(data=b"x" * 11)
        svc = _make_service(project_files, size_limit=10)

        with pytest.raises(ProjectFileTooLargeException, match="larger than 10 bytes"):
            await getattr(svc, operation)(
                PROJECT_FILE, "projects/b/p/files/artifacts/other.md", overwrite=True
            )
        project_files.put.assert_not_awaited()
        project_files.delete.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_write_returns_the_canonical_url(self):
        svc = _make_service(
            _make_project_files(), project=ProjectContext(url="projects/b/My Project")
        )

        url = await svc.write_file(
            "projects/b/My Project/files/artifacts/ä b.md", "x", overwrite=True
        )

        assert url == "projects/b/My%20Project/files/artifacts/%C3%A4%20b.md"

    @pytest.mark.asyncio
    async def test_traversal_out_of_the_project_is_not_dispatched_to_v2(self):
        dial_client = _make_dial_client()
        project_files = _make_project_files()
        svc = _make_service(project_files, dial_client=dial_client)

        await svc.download_file("projects/b/p/files/../../Other/files/x.md")

        project_files.stream.assert_not_called()
