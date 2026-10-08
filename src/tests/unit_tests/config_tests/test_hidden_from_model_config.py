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
    assert factory().hidden_from_model is None


@pytest.mark.parametrize("factory", _FACTORIES)
def test_accepts_subset_of_allowed_tools(factory) -> None:
    toolset = factory(allowed_tools=["a", "b"], hidden_from_model=["a"])
    assert toolset.hidden_from_model == ["a"]


@pytest.mark.parametrize("factory", _FACTORIES)
def test_accepts_any_names_without_allowed_tools(factory) -> None:
    assert factory(hidden_from_model=["a", "b"]).hidden_from_model == ["a", "b"]


@pytest.mark.parametrize("factory", _FACTORIES)
def test_empty_list_is_accepted(factory) -> None:
    assert factory(allowed_tools=["a"], hidden_from_model=[]).hidden_from_model == []


@pytest.mark.parametrize("factory", _FACTORIES)
def test_rejects_entries_missing_from_allowed_tools(factory) -> None:
    with pytest.raises(ValidationError, match="not present in allowed_tools: b"):
        factory(allowed_tools=["a"], hidden_from_model=["a", "b"])
