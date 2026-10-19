import pytest
from pydantic import ValidationError

from quickapp.config.application import nullify_preview_fields
from quickapp.config.toolsets.dial_app import DialAppToolSet
from quickapp.config.toolsets.dial_mcp import DialMCPToolSet
from quickapp.config.toolsets.mcp import MCPProtocol, MCPServerInfo, MCPToolSet
from quickapp.config.toolsets.mcp_tools_config import MCPToolConfig


def _mcp(**kwargs: object) -> MCPToolSet:
    return MCPToolSet(
        name="t",
        mcp_server_info=MCPServerInfo(url="https://s", protocol=MCPProtocol.streamable_http),
        **kwargs,  # type: ignore[arg-type]
    )


def _dial_mcp(**kwargs: object) -> DialMCPToolSet:
    return DialMCPToolSet(name="t", deployment_id="toolsets/t", **kwargs)  # type: ignore[arg-type]


def _dial_app(**kwargs: object) -> DialAppToolSet:
    return DialAppToolSet(name="t", deployment_id="app", **kwargs)  # type: ignore[arg-type]


_FACTORIES = [_mcp, _dial_mcp, _dial_app]


@pytest.mark.parametrize("factory", _FACTORIES)
def test_defaults_to_none(factory) -> None:
    assert factory().tools_config is None


@pytest.mark.parametrize("factory", _FACTORIES)
def test_parses_fixed_arguments_per_tool(factory) -> None:
    toolset = factory(tools_config={"a": {"fixed_arguments": {"project": "DIAL"}}})
    assert toolset.tools_config == {"a": MCPToolConfig(fixed_arguments={"project": "DIAL"})}


@pytest.mark.parametrize("factory", _FACTORIES)
def test_accepts_tools_listed_in_allowed_tools(factory) -> None:
    toolset = factory(allowed_tools=["a", "b"], tools_config={"a": {"fixed_arguments": {"x": 1}}})
    assert list(toolset.tools_config) == ["a"]


@pytest.mark.parametrize("factory", _FACTORIES)
def test_accepts_any_tool_without_allowed_tools(factory) -> None:
    config = {"a": {"fixed_arguments": {"limit": 50}}, "b": {"fixed_arguments": {"f": {"s": 1}}}}
    assert list(factory(tools_config=config).tools_config) == ["a", "b"]


@pytest.mark.parametrize("factory", _FACTORIES)
def test_rejects_tools_missing_from_allowed_tools(factory) -> None:
    with pytest.raises(ValidationError, match="not present in allowed_tools: b"):
        factory(allowed_tools=["a"], tools_config={"a": {}, "b": {}})


def test_tool_config_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="fixed_args"):
        MCPToolConfig.model_validate({"fixed_args": {"x": 1}})


@pytest.mark.parametrize("factory", _FACTORIES)
def test_nullified_when_preview_disabled(factory) -> None:
    toolset = factory(tools_config={"a": {"fixed_arguments": {"x": 1}}})
    nullify_preview_fields(toolset)
    assert toolset.tools_config is None
