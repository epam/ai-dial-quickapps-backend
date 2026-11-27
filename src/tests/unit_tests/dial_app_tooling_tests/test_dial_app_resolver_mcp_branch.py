import pytest

from quickapp.config.toolsets.authorization import AuthorizationType, MCPApiKeyAuthorization
from quickapp.config.toolsets.dial_app import DialAppToolSet
from quickapp.config.toolsets.mcp import MCPProtocol
from quickapp.config.toolsets.mcp_tools_config import MCPToolConfig

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


@pytest.mark.asyncio
async def test_mcp_toolset_carries_hidden_from_model():
    toolset = DialAppToolSet(
        name="app",
        deployment_id="dep",
        allowed_tools=["get_skill", "search"],
        hidden_from_model=["get_skill"],
    )
    resolver, context, _, _ = make_resolver(toolsets=[toolset], metadata=make_metadata(mcp=True))

    await resolver.resolve()

    assert context.resolved_mcp_toolsets[0].hidden_from_model == ["get_skill"]


@pytest.mark.asyncio
async def test_mcp_toolset_carries_tools_config(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ENABLE_PREVIEW_FEATURES", "true")
    toolset = DialAppToolSet(
        name="app",
        deployment_id="dep",
        tools_config={"search": {"fixed_arguments": {"project_key": "DIAL"}}},
    )
    resolver, context, _, _ = make_resolver(toolsets=[toolset], metadata=make_metadata(mcp=True))

    await resolver.resolve()

    assert context.resolved_mcp_toolsets[0].tools_config == {
        "search": MCPToolConfig(fixed_arguments={"project_key": "DIAL"})
    }


@pytest.mark.asyncio
async def test_mcp_branch_warns_when_both_form_flags_set(caplog: pytest.LogCaptureFixture):
    toolset = DialAppToolSet(
        name="app",
        deployment_id="dep",
        propagate_form_schema_to_choice=True,
        propagate_form_value_to_content=False,
    )
    resolver, _, _, _ = make_resolver(toolsets=[toolset], metadata=make_metadata(mcp=True))

    with caplog.at_level("WARNING", logger="quickapp.dial_app_tooling._dial_app_resolver"):
        await resolver.resolve()

    warnings = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert any("propagate_form_schema_to_choice" in w and "'app'" in w for w in warnings)
    assert any("propagate_form_value_to_content" in w and "'app'" in w for w in warnings)


@pytest.mark.asyncio
async def test_mcp_branch_warns_only_for_set_form_flag(caplog: pytest.LogCaptureFixture):
    toolset = DialAppToolSet(
        name="app",
        deployment_id="dep",
        propagate_form_schema_to_choice=True,
    )
    resolver, _, _, _ = make_resolver(toolsets=[toolset], metadata=make_metadata(mcp=True))

    with caplog.at_level("WARNING", logger="quickapp.dial_app_tooling._dial_app_resolver"):
        await resolver.resolve()

    warnings = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert any("propagate_form_schema_to_choice" in w for w in warnings)
    assert not any("propagate_form_value_to_content" in w for w in warnings)


@pytest.mark.asyncio
async def test_mcp_branch_no_form_warning_when_flags_unset(caplog: pytest.LogCaptureFixture):
    toolset = DialAppToolSet(name="app", deployment_id="dep")
    resolver, _, _, _ = make_resolver(toolsets=[toolset], metadata=make_metadata(mcp=True))

    with caplog.at_level("WARNING", logger="quickapp.dial_app_tooling._dial_app_resolver"):
        await resolver.resolve()

    warnings = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert not any("propagate_form" in w for w in warnings)
