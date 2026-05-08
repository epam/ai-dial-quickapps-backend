import pytest

from quickapp.config.toolsets.dial_app import DialAppToolSet

from ._helpers import make_metadata, make_resolver, make_tool_config


@pytest.mark.asyncio
async def test_mcp_branch_when_features_mcp_true():
    toolset = DialAppToolSet(name="app", deployment_id="dep")
    resolver, context, _, _ = make_resolver(
        toolsets=[toolset],
        metadata=make_metadata(mcp=True),
    )

    await resolver.resolve()

    assert len(context.resolved_mcp_toolsets) == 1
    assert len(context.resolved_deployment_tools) == 0
    assert not context.exceptions


@pytest.mark.asyncio
async def test_fallback_branch_when_features_mcp_false():
    toolset = DialAppToolSet(name="app", deployment_id="dep")
    resolver, context, _, _ = make_resolver(
        toolsets=[toolset],
        metadata=make_metadata(mcp=False),
        tool_config=make_tool_config(),
    )

    await resolver.resolve()

    assert len(context.resolved_mcp_toolsets) == 0
    assert len(context.resolved_deployment_tools) == 1


@pytest.mark.asyncio
async def test_fallback_branch_when_features_mcp_none():
    toolset = DialAppToolSet(name="app", deployment_id="dep")
    resolver, context, _, _ = make_resolver(
        toolsets=[toolset],
        metadata=make_metadata(mcp=None),
        tool_config=make_tool_config(),
    )

    await resolver.resolve()

    assert len(context.resolved_mcp_toolsets) == 0
    assert len(context.resolved_deployment_tools) == 1


@pytest.mark.asyncio
async def test_fallback_branch_when_features_absent():
    toolset = DialAppToolSet(name="app", deployment_id="dep")
    resolver, context, _, _ = make_resolver(
        toolsets=[toolset],
        metadata=make_metadata(with_features=False),
        tool_config=make_tool_config(),
    )

    await resolver.resolve()

    assert len(context.resolved_mcp_toolsets) == 0
    assert len(context.resolved_deployment_tools) == 1


@pytest.mark.asyncio
async def test_disabled_toolset_is_skipped():
    toolset = DialAppToolSet(name="app", deployment_id="dep", enabled=False)
    resolver, context, tool_config_service, _ = make_resolver(
        toolsets=[toolset],
        metadata=make_metadata(mcp=True),
    )

    await resolver.resolve()

    assert len(context.resolved_mcp_toolsets) == 0
    assert len(context.resolved_deployment_tools) == 0
    tool_config_service.get_deployment_metadata.assert_not_awaited()


@pytest.mark.asyncio
async def test_non_dial_app_toolsets_are_ignored():
    """The resolver only acts on DialAppToolSet entries; other types pass through."""
    from quickapp.config.toolsets.internal import InternalToolSet

    dial_app = DialAppToolSet(name="dial-app", deployment_id="dep")
    other = InternalToolSet(name="internal", tools=[])

    resolver, context, tool_config_service, _ = make_resolver(
        toolsets=[dial_app, other],
        metadata=make_metadata(mcp=True),
    )

    await resolver.resolve()

    # Only one metadata fetch — for the DialAppToolSet entry.
    assert tool_config_service.get_deployment_metadata.await_count == 1
    assert len(context.resolved_mcp_toolsets) == 1


def test_transport_defaults_to_auto():
    toolset = DialAppToolSet(name="app", deployment_id="dep")
    assert toolset.transport == "auto"
