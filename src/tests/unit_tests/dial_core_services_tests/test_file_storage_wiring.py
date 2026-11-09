"""DI wiring for ``FileStorage``: plain v1 storage without a project, the router with one."""

from unittest.mock import MagicMock

import pytest
from aidial_client import AsyncDial
from fastapi_injector import Injected, request_scope
from injector import Binder, InstanceProvider, Module
from starlette.testclient import TestClient

from quickapp.common.project_context import PROJECT_CONTEXT, ProjectContext
from quickapp.dial_core_services.dial_core_services_module import DialCoreServicesModule
from quickapp.dial_core_services.storage.file_storage import FileStorage
from quickapp.shared.config_resolvers.file_loading_size_limit_resolver import (
    FileLoadingSizeLimitResolver,
)
from tests.unit_tests.common.common import create_test_app


class _StubRequestModule(Module):
    def __init__(self, project: ProjectContext | None):
        self._project = project

    def configure(self, binder: Binder) -> None:
        # No spec: `deployments` (used by ProjectFilesClient) is set in AsyncDial.__init__.
        binder.bind(AsyncDial, to=lambda: MagicMock(), scope=request_scope)
        binder.bind(PROJECT_CONTEXT, to=InstanceProvider(self._project))
        binder.bind(
            FileLoadingSizeLimitResolver,
            to=InstanceProvider(MagicMock(spec=FileLoadingSizeLimitResolver)),
        )


def _storage_type(project: ProjectContext | None) -> str:
    app = create_test_app([DialCoreServicesModule(), _StubRequestModule(project)])

    @app.get("/storage")
    async def storage(file_storage: FileStorage = Injected(FileStorage)) -> str:  # type: ignore[type-abstract]
        return type(file_storage).__name__

    response = TestClient(app).get("/storage")
    assert response.status_code == 200
    return response.json()


@pytest.mark.parametrize(
    "project, expected",
    [(None, "V1FileStorage"), (ProjectContext(url="projects/b/p"), "RoutedFileStorage")],
)
def test_file_storage_routes_only_when_the_request_has_a_project(project, expected):
    assert _storage_type(project) == expected
