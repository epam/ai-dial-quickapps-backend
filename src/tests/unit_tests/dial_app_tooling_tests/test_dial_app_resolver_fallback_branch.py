import logging

import pytest

from quickapp.config.tools.base import AttachmentConfig
from quickapp.config.tools.deployment import ConversationMode
from quickapp.config.tools.tool_fallback import StopStrategyModel, ToolFallbackConfig
from quickapp.config.toolsets.dial_app import DialAppToolSet

from ._helpers import make_async_loader, make_metadata, make_resolver, make_tool_config


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
async def test_fallback_threads_conversation_mode_onto_synthetic_tool():
    toolset = DialAppToolSet(
        name="app",
        deployment_id="dep",
        conversation_mode=ConversationMode(resumable=True),
    )
    resolver, context, _, _ = make_resolver(
        toolsets=[toolset],
        metadata=make_metadata(mcp=False),
        tool_config=make_tool_config(),
    )

    await resolver.resolve()

    customised = context.resolved_deployment_tools[0]
    assert customised.conversation_mode is not None
    assert customised.conversation_mode.resumable is True


@pytest.mark.asyncio
async def test_fallback_conversation_mode_none_leaves_synthetic_default():
    toolset = DialAppToolSet(name="app", deployment_id="dep")
    resolver, context, _, _ = make_resolver(
        toolsets=[toolset],
        metadata=make_metadata(mcp=False),
        tool_config=make_tool_config(),
    )

    await resolver.resolve()

    assert context.resolved_deployment_tools[0].conversation_mode is None


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


@pytest.mark.asyncio
async def test_fallback_loader_dedupes_under_concurrent_resolution():
    """Two DialAppToolSets with the same deployment_id must trigger only one
    get_basic_tool_config call within a single resolve(). The resolver groups
    by deployment_id and serializes within a group; CacheService is not
    concurrency-safe, so without grouping concurrent get-misses would each
    invoke the loader."""
    toolsets = [
        DialAppToolSet(name="app-a", deployment_id="shared"),
        DialAppToolSet(name="app-b", deployment_id="shared"),
    ]
    resolver, context, tool_config_service, _ = make_resolver(
        toolsets=toolsets,
        metadata=make_metadata(mcp=False),
        tool_config=make_tool_config(),
    )
    # Replace the AsyncMock with one that yields control via asyncio.sleep(0),
    # making the cache race observable if grouping is missing.
    tool_config_service.get_basic_tool_config = make_async_loader(make_tool_config())

    await resolver.resolve()

    assert len(context.resolved_deployment_tools) == 2
    assert tool_config_service.get_basic_tool_config.await_count == 1


@pytest.mark.asyncio
async def test_metadata_fetch_dedupes_within_group():
    """Bonus win from grouping: two auto-transport toolsets pointing at the
    same deployment share one metadata fetch."""
    toolsets = [
        DialAppToolSet(name="app-a", deployment_id="shared"),
        DialAppToolSet(name="app-b", deployment_id="shared"),
    ]
    resolver, context, tool_config_service, _ = make_resolver(
        toolsets=toolsets,
        metadata=make_metadata(mcp=False),
        tool_config=make_tool_config(),
    )
    tool_config_service.get_deployment_metadata = make_async_loader(make_metadata(mcp=False))

    await resolver.resolve()

    assert len(context.resolved_deployment_tools) == 2
    assert tool_config_service.get_deployment_metadata.await_count == 1
