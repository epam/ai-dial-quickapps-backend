import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aidial_client.types.deployment import Features

from quickapp.common.exceptions import OrchestratorInitializationException
from quickapp.config.dial_deployment import DialDeploymentParameters
from quickapp.core.agent import OrchestratorCapabilities
from quickapp.core.agent._orchestrator_deployment_initializer import (
    _OrchestratorDeploymentInitializer,
)


def _make_deployment(
    deployment_id: str = "gpt-4",
    input_attachment_types: list[str] | None = None,
    defaults: dict | None = None,
    reasoning_efforts: list[str] | None = None,
    temperature: bool | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=deployment_id,
        input_attachment_types=input_attachment_types,
        defaults=defaults,
        features=Features(reasoning_efforts=reasoning_efforts or [], temperature=temperature),
    )


def _make_initializer(
    *,
    deployment_id: str = "gpt-4",
    fetch_metadata: AsyncMock | None = None,
    reasoning_effort: str | None = None,
    temperature: float | None = None,
) -> tuple[_OrchestratorDeploymentInitializer, AsyncMock, AsyncMock]:
    app_config = MagicMock()
    app_config.orchestrator.deployment.deployment_id = deployment_id
    app_config.orchestrator.deployment.parameters = DialDeploymentParameters(
        reasoning_effort=reasoning_effort, temperature=temperature
    )

    resolver = AsyncMock()
    tool_config_service = MagicMock()
    tool_config_service.get_deployment_metadata = resolver

    cache = MagicMock()
    cache.fetch_metadata = fetch_metadata or AsyncMock()

    static_tools_context = MagicMock()

    initializer = _OrchestratorDeploymentInitializer(
        app_config=app_config,
        tool_config_service=tool_config_service,
        orchestrator_deployment_cache=cache,
        static_tools_context=static_tools_context,
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


_LOGGER = "quickapp.core.agent._orchestrator_deployment_initializer"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("deployment", "reasoning_effort", "temperature"),
    [
        (_make_deployment(reasoning_efforts=["low", "high"]), "high", None),
        (_make_deployment(reasoning_efforts=[]), None, None),
        (_make_deployment(temperature=True), None, 0.2),
    ],
    ids=["reasoning_effort_advertised", "nothing_configured", "temperature_supported"],
)
async def test_no_warning_when_configured_parameters_are_supported(
    caplog: pytest.LogCaptureFixture,
    deployment: SimpleNamespace,
    reasoning_effort: str | None,
    temperature: float | None,
):
    initializer, _resolver, _fetch = _make_initializer(
        fetch_metadata=AsyncMock(return_value=deployment),
        reasoning_effort=reasoning_effort,
        temperature=temperature,
    )

    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        await initializer.initialize()

    assert caplog.records == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("deployment", "reasoning_effort", "temperature", "parameter"),
    [
        (_make_deployment(reasoning_efforts=["low"]), "high", None, "reasoning_effort"),
        (_make_deployment(reasoning_efforts=[]), "low", None, "reasoning_effort"),
        (_make_deployment(temperature=False), None, 0.2, "temperature"),
    ],
    ids=["reasoning_effort_unadvertised", "reasoning_efforts_empty", "temperature_unsupported"],
)
async def test_unsupported_parameter_is_logged_once_per_request(
    caplog: pytest.LogCaptureFixture,
    deployment: SimpleNamespace,
    reasoning_effort: str | None,
    temperature: float | None,
    parameter: str,
):
    initializer, _resolver, _fetch = _make_initializer(
        fetch_metadata=AsyncMock(return_value=deployment),
        reasoning_effort=reasoning_effort,
        temperature=temperature,
    )

    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        await initializer.initialize()

    assert len(caplog.records) == 1
    message = caplog.records[0].getMessage()
    assert f"Configured {parameter} is not supported by deployment gpt-4" in message
    # Logs carry structure, not content: the configured value is never logged.
    assert str(reasoning_effort or temperature) not in message
