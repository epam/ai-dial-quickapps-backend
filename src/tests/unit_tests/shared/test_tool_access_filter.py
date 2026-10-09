from unittest.mock import MagicMock

import httpx
import pytest
from fastapi_injector import Injected
from injector import Binder, Module
from starlette.testclient import TestClient

from quickapp.config.application import ApplicationConfig
from quickapp.config.tool_access_filter import ToolAccessFilterConfig
from quickapp.dial_core_services.deployment_names_service import DeploymentNamesCoreService
from quickapp.shared.user_access import ToolAccessFilter
from quickapp.shared.user_access.user_access_module import UserAccessModule
from tests.unit_tests.common.common import (
    create_app_configuration,
    create_test_app,
    make_access_filter,
    make_deployment_names_service,
)


def _app_config(enabled: bool = True) -> ApplicationConfig:
    config = create_app_configuration([])
    config.features.tool_access_filter = ToolAccessFilterConfig(enabled=enabled)
    return config


@pytest.mark.asyncio
async def test_disabled_filter_accepts_everything_and_never_calls_core() -> None:
    service = make_deployment_names_service(["a"])
    access = make_access_filter(_app_config(enabled=False), service)

    assert await access.is_accessible("anything")
    service.list_names.assert_not_called()


@pytest.mark.asyncio
async def test_unset_config_is_inert() -> None:
    service = make_deployment_names_service(["a"])
    access = make_access_filter(create_app_configuration([]), service)

    assert await access.is_accessible("anything")
    service.list_names.assert_not_called()


@pytest.mark.asyncio
async def test_only_listed_deployments_are_accessible() -> None:
    access = make_access_filter(
        _app_config(), make_deployment_names_service(["model-a", "model-b"])
    )

    assert await access.is_accessible("model-a")
    assert await access.is_accessible("model-b")
    assert not await access.is_accessible("model-c")


@pytest.mark.asyncio
async def test_quoted_and_unquoted_ids_match() -> None:
    access = make_access_filter(
        _app_config(), make_deployment_names_service(["applications/bucket/my%20app"])
    )

    assert await access.is_accessible("applications/bucket/my app")
    assert await access.is_accessible("applications/bucket/my%20app")
    assert not await access.is_accessible("applications/bucket/other")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [
        httpx.ConnectError("boom"),
        httpx.HTTPStatusError(
            "forbidden", request=httpx.Request("GET", "http://x"), response=httpx.Response(403)
        ),
        httpx.HTTPStatusError(
            "server error", request=httpx.Request("GET", "http://x"), response=httpx.Response(500)
        ),
        ValueError("unexpected shape"),
    ],
    ids=["transport", "403", "500", "bad-body"],
)
async def test_fails_open_when_core_cannot_be_queried(failure: Exception) -> None:
    access = make_access_filter(_app_config(), make_deployment_names_service(failure))

    assert await access.is_accessible("anything")


@pytest.mark.asyncio
async def test_unexpected_errors_are_not_swallowed() -> None:
    access = make_access_filter(
        _app_config(), make_deployment_names_service(RuntimeError("programming error"))
    )

    with pytest.raises(RuntimeError):
        await access.is_accessible("anything")


@pytest.mark.asyncio
async def test_one_core_call_per_filter_instance() -> None:
    service = make_deployment_names_service(["a"])
    access = make_access_filter(_app_config(), service)

    await access.is_accessible("a")
    await access.is_accessible("b")

    assert service.list_names.await_count == 1


class TestRequestScope:
    """`ToolAccessFilter` resolved through a real request-scoped `Injector`."""

    @staticmethod
    def _client(service: MagicMock) -> TestClient:
        config = _app_config()

        class _Deps(Module):
            def configure(self, binder: Binder) -> None:
                binder.bind(ApplicationConfig, to=config)
                binder.bind(DeploymentNamesCoreService, to=service)

        app = create_test_app([_Deps(), UserAccessModule()])

        @app.get("/access")
        async def get_access(
            first: ToolAccessFilter = Injected(ToolAccessFilter),
            second: ToolAccessFilter = Injected(ToolAccessFilter),
        ):
            assert first is second
            return {"accessible": await first.is_accessible("a")}

        return TestClient(app)

    def test_one_core_call_per_request_and_none_shared_across_requests(self) -> None:
        service = make_deployment_names_service(["a"])
        client = self._client(service)

        assert client.get("/access").json() == {"accessible": True}
        assert service.list_names.await_count == 1

        assert client.get("/access").json() == {"accessible": True}
        assert service.list_names.await_count == 2
