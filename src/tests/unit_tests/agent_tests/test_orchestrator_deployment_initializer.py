from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from quickapp.common.exceptions import (
    OrchestratorInitializationException,
    UnsupportedReasoningEffortException,
)
from quickapp.config.orchestrator_attachment_strategy import LazyOnDemandAttachmentStrategy
from quickapp.core.agent import OrchestratorCapabilities
from quickapp.core.agent._orchestrator_deployment_initializer import (
    _OrchestratorDeploymentInitializer,
)


def _make_deployment(
    deployment_id: str = "gpt-4",
    input_attachment_types: list[str] | None = None,
    defaults: dict | None = None,
    reasoning_efforts: list[str] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=deployment_id,
        input_attachment_types=input_attachment_types,
        defaults=defaults,
        features=SimpleNamespace(reasoning_efforts=reasoning_efforts or []),
    )


def _make_initializer(
    *,
    deployment_id: str = "gpt-4",
    fetch_metadata: AsyncMock | None = None,
    reasoning_effort: str | None = None,
    attachment_strategy: LazyOnDemandAttachmentStrategy | None = None,
) -> tuple[_OrchestratorDeploymentInitializer, AsyncMock, AsyncMock]:
    app_config = MagicMock()
    app_config.orchestrator.deployment.deployment_id = deployment_id
    app_config.orchestrator.deployment.parameters.reasoning_effort = reasoning_effort
    app_config.orchestrator.attachment_strategy = attachment_strategy

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
async def test_initialize_passes_app_accepted_types_from_lazy_on_demand_strategy():
    deployment = _make_deployment(
        deployment_id="gpt-4",
        input_attachment_types=["*/*"],
    )
    initializer, _resolver, _fetch_metadata = _make_initializer(
        fetch_metadata=AsyncMock(return_value=deployment),
        attachment_strategy=LazyOnDemandAttachmentStrategy(accepted_types=["image/*"]),
    )

    await initializer.initialize()

    assert initializer.capabilities.orchestrator_accepts_mime_type("application/pdf") is False
    assert initializer.capabilities.orchestrator_accepts_mime_type("image/png") is True


@pytest.mark.asyncio
async def test_resolver_and_deployment_id_passed_to_fetch_metadata():
    deployment = _make_deployment(deployment_id="my-app")
    initializer, resolver, fetch_metadata = _make_initializer(
        deployment_id="my-app",
        fetch_metadata=AsyncMock(return_value=deployment),
    )

    await initializer.initialize()

    fetch_metadata.assert_awaited_once_with(resolver, "my-app")


@pytest.mark.asyncio
async def test_no_issue_when_reasoning_effort_is_advertised():
    initializer, _resolver, _fetch = _make_initializer(
        fetch_metadata=AsyncMock(return_value=_make_deployment(reasoning_efforts=["low", "high"])),
        reasoning_effort="high",
    )

    await initializer.initialize()

    assert initializer.initialization_exceptions == []


@pytest.mark.asyncio
async def test_no_issue_when_no_reasoning_effort_is_configured():
    initializer, _resolver, _fetch = _make_initializer(
        fetch_metadata=AsyncMock(return_value=_make_deployment(reasoning_efforts=[])),
        reasoning_effort=None,
    )

    await initializer.initialize()

    assert initializer.initialization_exceptions == []


@pytest.mark.asyncio
async def test_unadvertised_reasoning_effort_is_reported_as_a_soft_issue():
    initializer, _resolver, _fetch = _make_initializer(
        deployment_id="gpt-4",
        fetch_metadata=AsyncMock(return_value=_make_deployment(reasoning_efforts=["low"])),
        reasoning_effort="high",
    )

    await initializer.initialize()

    assert len(initializer.initialization_exceptions) == 1
    issue = initializer.initialization_exceptions[0]
    assert isinstance(issue, UnsupportedReasoningEffortException)
    assert issue.is_hard is False
    assert issue.requested == "high"
    assert issue.supported == ["low"]
    assert "`low`" in str(issue)
    # The orchestrator deployment is never named in user-facing text.
    assert "gpt-4" not in str(issue)


@pytest.mark.asyncio
async def test_reasoning_effort_is_reported_when_deployment_advertises_none():
    """A deployment that advertises no reasoning efforts supports none of them."""
    initializer, _resolver, _fetch = _make_initializer(
        fetch_metadata=AsyncMock(return_value=_make_deployment(reasoning_efforts=[])),
        reasoning_effort="low",
    )

    await initializer.initialize()

    assert len(initializer.initialization_exceptions) == 1
    assert "does not advertise" in str(initializer.initialization_exceptions[0])
