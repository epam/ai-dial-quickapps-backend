import pytest

from quickapp.common.exceptions import ToolInitializationException
from quickapp.config.tools.base import AttachmentConfig
from quickapp.config.tools.tool_fallback import StopStrategyModel, ToolFallbackConfig
from quickapp.config.toolsets.dial_app import DialAppToolSet

from ._helpers import make_metadata, make_resolver, make_tool_config


@pytest.mark.asyncio
async def test_transport_mcp_succeeds_when_features_mcp_true():
    toolset = DialAppToolSet(name="app", deployment_id="dep", transport="mcp")
    resolver, context, tool_config_service, _ = make_resolver(
        toolsets=[toolset],
        metadata=make_metadata(mcp=True),
    )

    await resolver.resolve()

    tool_config_service.get_deployment_metadata.assert_awaited_once()
    assert len(context.resolved_mcp_toolsets) == 1
    assert len(context.resolved_deployment_tools) == 0
    assert not context.exceptions


@pytest.mark.asyncio
async def test_transport_mcp_raises_when_features_mcp_false():
    toolset = DialAppToolSet(name="my-app", deployment_id="dep", transport="mcp")
    resolver, context, tool_config_service, _ = make_resolver(
        toolsets=[toolset],
        metadata=make_metadata(mcp=False),
    )

    await resolver.resolve()

    assert len(context.resolved_mcp_toolsets) == 0
    assert len(context.resolved_deployment_tools) == 0
    assert len(context.exceptions) == 1
    exc = context.exceptions[0]
    assert isinstance(exc, ToolInitializationException)
    assert exc.toolset_name == "my-app"
    assert "transport=mcp requested but features.mcp is not advertised on dep" in exc.message
    tool_config_service.get_basic_tool_config.assert_not_awaited()


@pytest.mark.asyncio
async def test_transport_mcp_raises_when_features_absent():
    toolset = DialAppToolSet(name="my-app", deployment_id="dep", transport="mcp")
    resolver, context, tool_config_service, _ = make_resolver(
        toolsets=[toolset],
        metadata=make_metadata(with_features=False),
    )

    await resolver.resolve()

    assert len(context.resolved_mcp_toolsets) == 0
    assert len(context.exceptions) == 1
    exc = context.exceptions[0]
    assert isinstance(exc, ToolInitializationException)
    assert "transport=mcp requested but features.mcp is not advertised on dep" in exc.message
    tool_config_service.get_basic_tool_config.assert_not_awaited()


@pytest.mark.asyncio
async def test_transport_chat_completion_skips_metadata_fetch():
    toolset = DialAppToolSet(name="app", deployment_id="dep", transport="chat-completion")
    resolver, context, tool_config_service, _ = make_resolver(
        toolsets=[toolset],
        metadata=None,
        tool_config=make_tool_config(),
    )

    await resolver.resolve()

    tool_config_service.get_deployment_metadata.assert_not_awaited()
    assert len(context.resolved_mcp_toolsets) == 0
    assert len(context.resolved_deployment_tools) == 1
    assert not context.exceptions


@pytest.mark.asyncio
async def test_transport_chat_completion_propagates_customisation():
    custom_attachment = AttachmentConfig(supported_types=["application/pdf"])
    custom_fallback = ToolFallbackConfig(
        strategies=[StopStrategyModel()],
        display_error_in_stage=False,
    )
    toolset = DialAppToolSet(
        name="app",
        deployment_id="dep",
        transport="chat-completion",
        attachment=custom_attachment,
        fallback_configuration=custom_fallback,
    )
    resolver, context, _, _ = make_resolver(
        toolsets=[toolset],
        metadata=None,
        tool_config=make_tool_config(),
    )

    await resolver.resolve()

    customised = context.resolved_deployment_tools[0]
    assert customised.attachment == custom_attachment
    assert customised.fallback_configuration == custom_fallback
