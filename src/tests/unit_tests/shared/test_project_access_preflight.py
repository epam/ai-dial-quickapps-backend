"""``_ProjectAccessPreflight`` against a real ``ProjectFilesClient``; HTTP via pytest-httpx."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from aidial_client import AsyncDial, DialException
from aidial_sdk.exceptions import HTTPException as DialHTTPException

from quickapp.common.project_context import ProjectContext
from quickapp.core.application._exception_message_resolver import resolve_exception
from quickapp.core.application._quick_app_completion import _outgoing_status_code
from quickapp.dial_app_tooling._dial_app_resolver import _DialAppResolver
from quickapp.dial_core_services._project_files import ProjectFilesClient
from quickapp.shared.project._project_access_preflight import _ProjectAccessPreflight

BASE_URL = "http://test-dial"
PROJECT = ProjectContext(url="projects/b/My Project")
METADATA_URL = f"{BASE_URL}/v2/metadata/projects/b/My%20Project"


def _preflight(project: ProjectContext | None = PROJECT) -> _ProjectAccessPreflight:
    client = ProjectFilesClient(AsyncDial(base_url=BASE_URL, api_key="per-request", max_retries=0))
    return _ProjectAccessPreflight(project=project, project_files=client)


def test_runs_before_the_dial_app_resolver() -> None:
    assert _ProjectAccessPreflight.order < _DialAppResolver.order


@pytest.mark.asyncio
async def test_no_project_makes_no_call() -> None:
    project_files = MagicMock(spec=ProjectFilesClient)
    project_files.project_metadata = AsyncMock()

    await _ProjectAccessPreflight(project=None, project_files=project_files).initialize()

    project_files.project_metadata.assert_not_awaited()


@pytest.mark.asyncio
async def test_access_passes_with_one_call_and_the_request_key(httpx_mock) -> None:
    httpx_mock.add_response(method="GET", url=METADATA_URL, json={"etag": "e"})

    await _preflight().initialize()

    requests = httpx_mock.get_requests()
    assert len(requests) == 1
    assert requests[0].headers["api-key"] == "per-request"


@pytest.mark.parametrize(
    "core_status, code, message",
    [
        (
            403,
            "project_access_denied",
            "An administrator must approve the app's access to projects (resource dependencies).",
        ),
        (
            404,
            "project_not_found",
            "The project was not found. It may have been deleted or renamed.",
        ),
    ],
)
@pytest.mark.asyncio
async def test_no_access_fails_with_a_wire_error(
    httpx_mock, core_status: int, code: str, message: str
) -> None:
    httpx_mock.add_response(method="GET", url=METADATA_URL, status_code=core_status)

    with pytest.raises(DialHTTPException) as excinfo:
        await _preflight().initialize()

    error = excinfo.value
    assert (error.status_code, error.code, error.display_message) == (core_status, code, message)
    # The completion's error handler passes status, code and text through unchanged.
    resolved = resolve_exception(error)
    assert resolved.message == message
    assert resolved.details.code == code
    assert _outgoing_status_code(resolved) == core_status


@pytest.mark.parametrize("core_status", [401, 500])
@pytest.mark.asyncio
async def test_other_failures_propagate_as_today(httpx_mock, core_status: int) -> None:
    httpx_mock.add_response(method="GET", url=METADATA_URL, status_code=core_status)

    with pytest.raises(DialException) as excinfo:
        await _preflight().initialize()

    assert excinfo.value.status_code == core_status
