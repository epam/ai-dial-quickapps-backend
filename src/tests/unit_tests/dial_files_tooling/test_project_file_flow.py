"""End to end in a project chat: a file tool, ``HomePathResolver`` and ``DialFileService``
down to the v2 project API (real ``ProjectFilesClient``; HTTP via pytest-httpx)."""

from unittest.mock import MagicMock

import pytest
from aidial_client import AsyncDial

from quickapp.common.project_context import ProjectContext
from quickapp.common.state_holder import StateHolder
from quickapp.config.application import StageDisplayLevel
from quickapp.dial_core_services._project_files import ProjectFilesClient
from quickapp.dial_core_services.dial_file_service import DialFileService
from quickapp.dial_core_services.storage._project_file_storage import ProjectFileStorage
from quickapp.dial_core_services.storage._routed_file_storage import RoutedFileStorage
from quickapp.dial_core_services.storage._v1_file_storage import V1FileStorage
from quickapp.dial_files_tooling._find_files_tool import _FindFilesTool
from quickapp.dial_files_tooling._list_files_tool import _ListFilesTool
from quickapp.dial_files_tooling._read_file_lines_tool import _ReadFileLinesTool
from quickapp.dial_files_tooling._tool_configs import (
    FIND_FILES_TOOL_CONFIG,
    LIST_FILES_TOOL_CONFIG,
    READ_FILE_LINES_TOOL_CONFIG,
    WRITE_FILE_TOOL_CONFIG,
)
from quickapp.dial_files_tooling._write_file_tool import _WriteFileTool
from quickapp.shared.config_resolvers.file_loading_size_limit_resolver import (
    FileLoadingSizeLimitResolver,
)
from tests.unit_tests.dial_files_tooling._helpers import make_config, make_tool

BASE_URL = "http://test-dial"
PROJECT = ProjectContext(url="projects/b/My Project")
FILE_URL = f"{BASE_URL}/v2/projects/b/My%20Project/files/artifacts/notes.md"


def _service() -> DialFileService:
    dial = AsyncDial(base_url=BASE_URL, api_key="per-request", max_retries=0)
    size_limit = MagicMock(spec=FileLoadingSizeLimitResolver)
    size_limit.resolve.return_value = 1024 * 1024
    storage = RoutedFileStorage(
        V1FileStorage(dial, size_limit),
        ProjectFileStorage(ProjectFilesClient(dial), size_limit, PROJECT),
        PROJECT,
    )
    return DialFileService(dial_client=dial, storage=storage, state_holder=StateHolder())


@pytest.mark.asyncio
async def test_write_then_read_a_relative_path_lands_in_artifacts(httpx_mock):
    # Create-only write: the file is absent -> one plain PUT.
    httpx_mock.add_response(method="GET", url=FILE_URL, status_code=404)
    httpx_mock.add_response(method="PUT", url=FILE_URL, json={})
    httpx_mock.add_response(
        method="GET", url=FILE_URL, content=b"line 1\nline 2\n", headers={"etag": "f-etag"}
    )
    service = _service()
    # agent_home_dir is ignored in a project: the home is the project's artifacts/.
    config = make_config(agent_home_dir="workspace/")
    write = make_tool(
        _WriteFileTool, WRITE_FILE_TOOL_CONFIG, service=service, config=config, project=PROJECT
    )
    read = make_tool(
        _ReadFileLinesTool,
        READ_FILE_LINES_TOOL_CONFIG,
        service=service,
        config=config,
        project=PROJECT,
    )

    written = await write.arun(
        "call-1", stage_level=StageDisplayLevel.NONE, path="notes.md", content="line 1\nline 2\n"
    )
    result = await read.arun(
        "call-2", stage_level=StageDisplayLevel.NONE, path="notes.md", start_line=0, end_line=10
    )

    assert written.content == "File written: notes.md"
    assert result.content == "line 1\nline 2"
    put = httpx_mock.get_requests(method="PUT")[0]
    assert "If-Match" not in put.headers
    assert b"line 1\nline 2\n" in put.content
    # Nothing went to the v1 files API or the appdata lookup.
    assert all("/v1/" not in str(request.url) for request in httpx_mock.get_requests())


@pytest.mark.asyncio
async def test_a_conversation_is_not_read_and_core_is_not_called(httpx_mock):
    read = make_tool(
        _ReadFileLinesTool, READ_FILE_LINES_TOOL_CONFIG, service=_service(), project=PROJECT
    )

    result = await read.arun(
        "call-1",
        stage_level=StageDisplayLevel.NONE,
        path="projects/b/My Project/files/conversations/chat.json",
        start_line=0,
        end_line=10,
    )

    assert "access denied" in result.content
    # The real reason, not "the app has no permission": another path may work.
    assert "only the current project's context/ and artifacts/ folders are readable" in (
        result.content
    )
    assert httpx_mock.get_requests() == []


@pytest.mark.asyncio
async def test_listing_the_project_folder_shows_only_context_and_artifacts(httpx_mock):
    list_files = make_tool(
        _ListFilesTool, LIST_FILES_TOOL_CONFIG, service=_service(), project=PROJECT
    )

    result = await list_files.arun(
        "call-1", stage_level=StageDisplayLevel.NONE, path="projects/b/My Project/files/"
    )

    # Both by their full URL: the home (artifacts/) too, though other paths are home-relative.
    assert "projects/b/My Project/files/context/" in result.content
    assert "projects/b/My Project/files/artifacts/" in result.content
    assert "conversations" not in result.content
    assert "PROJECT.md" not in result.content
    # The layout is fixed, so the listing needs no request.
    assert httpx_mock.get_requests() == []


@pytest.mark.asyncio
async def test_a_recursive_search_from_the_project_folder_never_lists_conversations(httpx_mock):
    root = "projects/b/My%20Project/files/"
    listings = {
        "context": [
            {"url": f"{root}context/tickets.csv", "nodeType": "ITEM"},
            {"url": f"{root}context/sub", "nodeType": "FOLDER"},
        ],
        "context/sub": [{"url": f"{root}context/sub/a.md", "nodeType": "ITEM"}],
        "artifacts": [{"url": f"{root}artifacts/notes.md", "nodeType": "ITEM"}],
    }
    for folder, items in listings.items():
        httpx_mock.add_response(
            method="GET", url=f"{BASE_URL}/v2/metadata/{root}{folder}", json={"items": items}
        )
    find_files = make_tool(
        _FindFilesTool, FIND_FILES_TOOL_CONFIG, service=_service(), project=PROJECT
    )

    result = await find_files.arun(
        "call-1",
        stage_level=StageDisplayLevel.NONE,
        pattern="**",
        path="projects/b/My Project/files/",
        max_depth=3,
    )

    assert "projects/b/My Project/files/context/tickets.csv" in result.content
    assert "projects/b/My Project/files/context/sub/a.md" in result.content
    assert "notes.md" in result.content
    assert "conversations" not in result.content
    assert "PROJECT.md" not in result.content
    # One request per level of context/ and artifacts/: none for the project folder itself
    # (its two entries are fixed), none for conversations/.
    assert sorted(str(request.url) for request in httpx_mock.get_requests()) == sorted(
        f"{BASE_URL}/v2/metadata/{root}{folder}" for folder in listings
    )
