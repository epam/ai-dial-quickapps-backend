import pytest
from pydantic import ValidationError

from quickapp.config.toolsets.dial_app import DialAppToolSet
from quickapp.config.toolsets.dial_mcp import DialMCPToolSet
from quickapp.config.toolsets.mcp import MCPProtocol, MCPServerInfo, MCPToolSet


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
    assert factory().fixed_arguments is None


@pytest.mark.parametrize("factory", _FACTORIES)
def test_accepts_tools_listed_in_allowed_tools(factory) -> None:
    toolset = factory(allowed_tools=["a", "b"], fixed_arguments={"a": {"project": "DIAL"}})
    assert toolset.fixed_arguments == {"a": {"project": "DIAL"}}


@pytest.mark.parametrize("factory", _FACTORIES)
def test_accepts_any_tool_without_allowed_tools(factory) -> None:
    fixed = {"a": {"limit": 50}, "b": {"filters": {"state": "open"}}}
    assert factory(fixed_arguments=fixed).fixed_arguments == fixed


@pytest.mark.parametrize("factory", _FACTORIES)
def test_rejects_tools_missing_from_allowed_tools(factory) -> None:
    with pytest.raises(ValidationError, match="not present in allowed_tools: b"):
        factory(allowed_tools=["a"], fixed_arguments={"a": {"x": 1}, "b": {"x": 2}})
