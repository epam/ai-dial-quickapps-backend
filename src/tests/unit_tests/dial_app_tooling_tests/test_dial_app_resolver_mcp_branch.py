import pytest

from quickapp.config.toolsets.authorization import AuthorizationType, MCPApiKeyAuthorization
from quickapp.config.toolsets.dial_app import DialAppToolSet
from quickapp.config.toolsets.mcp import MCPProtocol

from ._helpers import make_metadata, make_resolver


@pytest.mark.asyncio
async def test_mcp_toolset_url_uses_correct_path():
    toolset = DialAppToolSet(name="app", deployment_id="my-deployment")
    resolver, context, _, _ = make_resolver(
        toolsets=[toolset],
        metadata=make_metadata(mcp=True),
        dial_url="https://dial.example",
    )

    await resolver.resolve()

    built = context.resolved_mcp_toolsets[0]
    assert built.mcp_server_info.url == "https://dial.example/v1/deployments/my-deployment/mcp"


@pytest.mark.asyncio
async def test_mcp_toolset_protocol_is_streamable_http():
    toolset = DialAppToolSet(name="app", deployment_id="dep")
    resolver, context, _, _ = make_resolver(toolsets=[toolset], metadata=make_metadata(mcp=True))

    await resolver.resolve()

    assert context.resolved_mcp_toolsets[0].mcp_server_info.protocol == MCPProtocol.streamable_http


@pytest.mark.asyncio
async def test_mcp_toolset_carries_api_key_authorization():
    toolset = DialAppToolSet(name="app", deployment_id="dep")
    resolver, context, _, _ = make_resolver(
        toolsets=[toolset],
        metadata=make_metadata(mcp=True),
        api_key="secret-key",
    )

    await resolver.resolve()

    auth = context.resolved_mcp_toolsets[0].mcp_server_info.authorization
    assert isinstance(auth, MCPApiKeyAuthorization)
    assert auth.type == AuthorizationType.api_key
    assert auth.key == "secret-key"
    assert auth.name == "Api-Key"


@pytest.mark.asyncio
async def test_mcp_toolset_copies_fields_from_source():
    toolset = DialAppToolSet(
        name="my-app",
        description="a test app",
        deployment_id="dep",
        allowed_tools=["search", "classify"],
    )
    resolver, context, _, _ = make_resolver(toolsets=[toolset], metadata=make_metadata(mcp=True))

    await resolver.resolve()

    built = context.resolved_mcp_toolsets[0]
    assert built.name == "my-app"
    assert built.description == "a test app"
    assert built.enabled is True
    assert built.allowed_tools == ["search", "classify"]
    assert built.attachment == toolset.attachment
    assert built.fallback_configuration == toolset.fallback_configuration
