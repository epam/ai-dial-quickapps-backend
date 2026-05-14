from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from quickapp.agent._orchestrator_deployment_initializer import _OrchestratorDeploymentInitializer
from quickapp.agent.orchestrator_capabilities import OrchestratorCapabilities


def _make_app_config(deployment_id: str = "gpt-4") -> MagicMock:
    app_config = MagicMock()
    app_config.orchestrator.deployment.deployment_id = deployment_id
    return app_config


def _make_deployment(
    deployment_id: str = "gpt-4",
    input_attachment_types: list[str] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(id=deployment_id, input_attachment_types=input_attachment_types)


def _make_initializer(
    deployment_id: str = "gpt-4",
    cache_return_value: object = None,
) -> tuple[_OrchestratorDeploymentInitializer, AsyncMock, AsyncMock]:
    tool_config_service = MagicMock()
    tool_config_service.get_deployment_metadata = AsyncMock()

    cache = MagicMock()
    cache.get = AsyncMock(return_value=cache_return_value)

    initializer = _OrchestratorDeploymentInitializer(
        app_config=_make_app_config(deployment_id),
        tool_config_service=tool_config_service,
        orchestrator_deployment_cache=cache,
    )
    return initializer, tool_config_service.get_deployment_metadata, cache.get


@pytest.mark.asyncio
async def test_initialize_populates_capabilities_from_cache():
    deployment = _make_deployment(
        deployment_id="gpt-4",
        input_attachment_types=["application/pdf"],
    )
    initializer, _resolver, _cache_get = _make_initializer(
        deployment_id="gpt-4", cache_return_value=deployment
    )

    await initializer.initialize()

    assert isinstance(initializer.capabilities, OrchestratorCapabilities)
    assert initializer.capabilities.deployment_id == "gpt-4"
    assert initializer.capabilities.input_attachment_types == ["application/pdf"]


@pytest.mark.asyncio
async def test_initialize_raises_when_cache_returns_none():
    initializer, _resolver, _cache_get = _make_initializer(cache_return_value=None)

    with pytest.raises(RuntimeError, match="returned no model"):
        await initializer.initialize()


def test_capabilities_property_raises_before_initialize():
    initializer, _resolver, _cache_get = _make_initializer()

    with pytest.raises(RuntimeError, match="accessed before"):
        _ = initializer.capabilities


@pytest.mark.asyncio
async def test_cache_key_and_resolver_passed_to_cache_get():
    deployment = _make_deployment(deployment_id="my-app")
    initializer, resolver, cache_get = _make_initializer(
        deployment_id="my-app", cache_return_value=deployment
    )

    await initializer.initialize()

    cache_get.assert_awaited_once_with(
        "orchestrator_deployment_my-app",
        resolver,
        "my-app",
    )
