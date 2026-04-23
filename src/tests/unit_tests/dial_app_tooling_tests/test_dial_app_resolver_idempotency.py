import pytest

from quickapp.config.toolsets.dial_app import DialAppToolSet

from ._helpers import make_metadata, make_resolver, make_tool_config


@pytest.mark.asyncio
async def test_resolve_is_idempotent_within_one_instance():
    toolset = DialAppToolSet(name="app", deployment_id="dep")
    resolver, context, tool_config_service, deployment_cache = make_resolver(
        toolsets=[toolset],
        metadata=make_metadata(mcp=False),
        tool_config=make_tool_config(),
    )

    await resolver.resolve()
    await resolver.resolve()
    await resolver.resolve()

    # Metadata fetch runs exactly once across repeated awaits.
    assert tool_config_service.get_deployment_metadata.await_count == 1
    # Cache loader also ran exactly once.
    assert tool_config_service.get_basic_tool_config.await_count == 1
    # Cache itself was consulted exactly once (second+ calls short-circuit via _resolved).
    assert deployment_cache.get.await_count == 1
    # Context is not double-populated.
    assert len(context.resolved_deployment_tools) == 1


@pytest.mark.asyncio
async def test_initialize_delegates_to_resolve():
    toolset = DialAppToolSet(name="app", deployment_id="dep")
    resolver, context, tool_config_service, _ = make_resolver(
        toolsets=[toolset],
        metadata=make_metadata(mcp=True),
    )

    await resolver.initialize()

    assert tool_config_service.get_deployment_metadata.await_count == 1
    assert len(context.resolved_mcp_toolsets) == 1


@pytest.mark.asyncio
async def test_idempotency_flag_survives_exceptions():
    """If resolve() raises mid-flight, the flag must still flip so subsequent
    awaits don't re-run half-completed work."""
    toolset = DialAppToolSet(name="app", deployment_id="dep")
    resolver, context, tool_config_service, _ = make_resolver(
        toolsets=[toolset],
        metadata=RuntimeError("boom"),
    )

    await resolver.resolve()
    await resolver.resolve()

    # Single call despite double-await.
    assert tool_config_service.get_deployment_metadata.await_count == 1
    # Error was recorded once.
    assert len(context.exceptions) == 1
