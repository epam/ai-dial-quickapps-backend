import pytest

from quickapp.common.exceptions import ToolInitializationException
from quickapp.config.toolsets.dial_app import DialAppToolSet

from ._helpers import make_metadata, make_resolver, make_tool_config


@pytest.mark.asyncio
async def test_metadata_fetch_runtime_error_becomes_initialization_exception():
    toolset = DialAppToolSet(name="my-app", deployment_id="dep")
    resolver, context, _, _ = make_resolver(
        toolsets=[toolset],
        metadata=RuntimeError("Neither deployment nor application found for 'dep'"),
    )

    await resolver.resolve()

    assert len(context.exceptions) == 1
    exc = context.exceptions[0]
    assert isinstance(exc, ToolInitializationException)
    assert exc.toolset_name == "my-app"
    assert "Neither deployment nor application found" in exc.message


@pytest.mark.asyncio
async def test_metadata_fetch_generic_exception_is_wrapped():
    toolset = DialAppToolSet(name="my-app", deployment_id="dep")
    resolver, context, _, _ = make_resolver(
        toolsets=[toolset],
        metadata=ValueError("unexpected failure"),
    )

    await resolver.resolve()

    assert len(context.exceptions) == 1
    assert context.exceptions[0].toolset_name == "my-app"


@pytest.mark.asyncio
async def test_fallback_loader_returning_none_raises_initialization_exception():
    toolset = DialAppToolSet(name="my-app", deployment_id="dep")
    resolver, context, _, _ = make_resolver(
        toolsets=[toolset],
        metadata=make_metadata(mcp=False),
        tool_config=None,
    )

    await resolver.resolve()

    assert len(context.exceptions) == 1
    exc = context.exceptions[0]
    assert exc.toolset_name == "my-app"
    assert "No tool config for dep" in exc.message


@pytest.mark.asyncio
async def test_first_toolset_failing_does_not_abort_later_toolsets():
    failing = DialAppToolSet(name="failing", deployment_id="bad")
    good = DialAppToolSet(name="good", deployment_id="ok")
    resolver, context, tool_config_service, _ = make_resolver(
        toolsets=[failing, good],
        metadata=None,  # default: returns None -> placeholder
        tool_config=make_tool_config(),
    )

    async def metadata_side_effect(deployment_id: str):
        if deployment_id == "bad":
            raise RuntimeError(f"Neither deployment nor application found for '{deployment_id}'")
        return make_metadata(mcp=True)

    tool_config_service.get_deployment_metadata.side_effect = metadata_side_effect

    await resolver.resolve()

    # Both toolsets were visited.
    assert tool_config_service.get_deployment_metadata.await_count == 2
    # One error captured, one MCP toolset resolved.
    assert len(context.exceptions) == 1
    assert context.exceptions[0].toolset_name == "failing"
    assert len(context.resolved_mcp_toolsets) == 1
    assert context.resolved_mcp_toolsets[0].name == "good"


@pytest.mark.asyncio
async def test_tool_initialization_exception_from_inside_fallback_is_recorded_as_is():
    """If the resolver itself raises ToolInitializationException (e.g. tool_config is None),
    it's recorded without being re-wrapped — matches existing initializer pattern."""
    toolset = DialAppToolSet(name="my-app", deployment_id="dep")
    resolver, context, _, _ = make_resolver(
        toolsets=[toolset],
        metadata=make_metadata(mcp=False),
        tool_config=None,
    )

    await resolver.resolve()

    assert len(context.exceptions) == 1
    assert isinstance(context.exceptions[0], ToolInitializationException)
    # Message is the resolver's own message, not wrapped.
    assert "No tool config" in context.exceptions[0].message
