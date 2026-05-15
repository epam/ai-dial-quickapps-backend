from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from quickapp.agent._orchestrator_deployment_initializer import _OrchestratorDeploymentInitializer
from quickapp.agent.orchestrator_capabilities import OrchestratorCapabilities
from quickapp.common.exceptions import OrchestratorInitializationException


def _make_deployment(
    deployment_id: str = "gpt-4",
    input_attachment_types: list[str] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(id=deployment_id, input_attachment_types=input_attachment_types)


def _make_initializer(
    *,
    deployment_id: str = "gpt-4",
    fetch_metadata: AsyncMock | None = None,
) -> tuple[_OrchestratorDeploymentInitializer, AsyncMock, AsyncMock]:
    app_config = MagicMock()
    app_config.orchestrator.deployment.deployment_id = deployment_id

    resolver = AsyncMock()
    tool_config_service = MagicMock()
    tool_config_service.get_deployment_metadata = resolver

    cache = MagicMock()
    cache.fetch_metadata = fetch_metadata or AsyncMock()

    initializer = _OrchestratorDeploymentInitializer(
        app_config=app_config,
        tool_config_service=tool_config_service,
        orchestrator_deployment_cache=cache,
    )
    return initializer, resolver, cache.fetch_metadata


@pytest.mark.asyncio
async def test_initialize_populates_capabilities_from_cache():
    deployment = _make_deployment(
        deployment_id="gpt-4",
        input_attachment_types=["application/pdf"],
    )
    initializer, _resolver, _fetch_metadata = _make_initializer(
        fetch_metadata=AsyncMock(return_value=deployment),
    )

    await initializer.initialize()

    assert isinstance(initializer.capabilities, OrchestratorCapabilities)
    assert initializer.capabilities.deployment_id == "gpt-4"
    assert initializer.capabilities.input_attachment_types == ["application/pdf"]


@pytest.mark.asyncio
async def test_initialize_propagates_orchestrator_initialization_exception_from_cache():
    initializer, _resolver, _fetch_metadata = _make_initializer(
        fetch_metadata=AsyncMock(
            side_effect=OrchestratorInitializationException(
                message="No deployment metadata", deployment_id="gpt-4"
            )
        ),
    )

    with pytest.raises(OrchestratorInitializationException, match="No deployment metadata"):
        await initializer.initialize()


def test_capabilities_property_raises_before_initialize():
    initializer, _resolver, _fetch_metadata = _make_initializer()

    with pytest.raises(RuntimeError, match="accessed before"):
        _ = initializer.capabilities


@pytest.mark.asyncio
async def test_resolver_and_deployment_id_passed_to_fetch_metadata():
    deployment = _make_deployment(deployment_id="my-app")
    initializer, resolver, fetch_metadata = _make_initializer(
        deployment_id="my-app",
        fetch_metadata=AsyncMock(return_value=deployment),
    )

    await initializer.initialize()

    fetch_metadata.assert_awaited_once_with(resolver, "my-app")
