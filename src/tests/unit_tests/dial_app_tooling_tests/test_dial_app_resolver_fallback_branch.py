import logging

import pytest

from quickapp.config.tools.base import AttachmentConfig
from quickapp.config.tools.tool_fallback import StopStrategyModel, ToolFallbackConfig
from quickapp.config.toolsets.dial_app import DialAppToolSet

from ._helpers import make_metadata, make_resolver, make_tool_config


@pytest.mark.asyncio
async def test_fallback_uses_cache_key_shared_with_simple_deployment_tool():
    toolset = DialAppToolSet(name="app", deployment_id="dep-1")
    resolver, _, _, deployment_cache = make_resolver(
        toolsets=[toolset],
        metadata=make_metadata(mcp=False),
        tool_config=make_tool_config(),
    )

    await resolver.resolve()

    # Cache key must match what _DeploymentToolInitializer.__init_simple_deployment_tool
    # uses so the two paths share cache entries.
    cache_keys = [call.args[0] for call in deployment_cache.get.await_args_list]
    assert cache_keys == ["basic_config_dep-1"]


@pytest.mark.asyncio
async def test_fallback_loader_skipped_on_cache_hit():
    toolsets = [
        DialAppToolSet(name="app-a", deployment_id="shared"),
        DialAppToolSet(name="app-b", deployment_id="shared"),
    ]
    resolver, context, tool_config_service, _ = make_resolver(
        toolsets=toolsets,
        metadata=make_metadata(mcp=False),
        tool_config=make_tool_config(),
    )

    await resolver.resolve()

    assert len(context.resolved_deployment_tools) == 2
    assert tool_config_service.get_basic_tool_config.await_count == 1


@pytest.mark.asyncio
async def test_fallback_model_copy_overrides_attachment_and_fallback_configuration():
    custom_attachment = AttachmentConfig(supported_types=["application/pdf"])
    custom_fallback = ToolFallbackConfig(
        strategies=[StopStrategyModel()],
        display_error_in_stage=False,
    )
    toolset = DialAppToolSet(
        name="app",
        deployment_id="dep",
        attachment=custom_attachment,
        fallback_configuration=custom_fallback,
    )
    resolver, context, _, _ = make_resolver(
        toolsets=[toolset],
        metadata=make_metadata(mcp=False),
        tool_config=make_tool_config(),
    )

    await resolver.resolve()

    customised = context.resolved_deployment_tools[0]
    assert customised.attachment == custom_attachment
    assert customised.fallback_configuration == custom_fallback


@pytest.mark.asyncio
async def test_fallback_warns_when_allowed_tools_set(caplog):
    toolset = DialAppToolSet(
        name="my-toolset",
        deployment_id="dep",
        allowed_tools=["search"],
    )
    resolver, _, _, _ = make_resolver(
        toolsets=[toolset],
        metadata=make_metadata(mcp=False),
        tool_config=make_tool_config(),
    )

    resolver_logger = "quickapp.dial_app_tooling._dial_app_resolver"
    with caplog.at_level(logging.WARNING, logger=resolver_logger):
        await resolver.resolve()

    resolver_warnings = [
        r for r in caplog.records if r.levelno == logging.WARNING and r.name == resolver_logger
    ]
    assert len(resolver_warnings) == 1
    assert "my-toolset" in resolver_warnings[0].getMessage()
    assert "allowed_tools" in resolver_warnings[0].getMessage()


@pytest.mark.asyncio
async def test_fallback_no_warning_when_allowed_tools_unset(caplog):
    toolset = DialAppToolSet(name="my-toolset", deployment_id="dep")
    resolver, _, _, _ = make_resolver(
        toolsets=[toolset],
        metadata=make_metadata(mcp=False),
        tool_config=make_tool_config(),
    )

    resolver_logger = "quickapp.dial_app_tooling._dial_app_resolver"
    with caplog.at_level(logging.WARNING, logger=resolver_logger):
        await resolver.resolve()

    resolver_warnings = [
        r for r in caplog.records if r.levelno == logging.WARNING and r.name == resolver_logger
    ]
    assert resolver_warnings == []
