import pytest
from pydantic import ValidationError

from quickapp.config.toolsets.deployment import DeploymentToolSet
from quickapp.config.toolsets.dial_app import DialAppToolSet
from quickapp.config.toolsets.dial_mcp import DialMCPToolSet
from quickapp.config.toolsets.mcp import MCPProtocol, MCPServerInfo, MCPToolSet
from quickapp.config.toolsets.rest_api import RestApiToolSet


def _rest(**kwargs):
    return RestApiToolSet(name="rest", tools=[], **kwargs)


def test_forwarded_headers_default_is_unset():
    assert _rest().forwarded_headers is None


def test_names_are_lowercased_and_deduplicated_in_order():
    toolset = _rest(forwarded_headers=["X-Tenant-Id", "x-request-id", "X-TENANT-ID"])

    assert toolset.forwarded_headers == ["x-tenant-id", "x-request-id"]


def test_empty_list_is_kept_distinct_from_unset():
    assert _rest(forwarded_headers=[]).forwarded_headers == []


@pytest.mark.parametrize(
    "name",
    ["authorization", "api-key", "traceparent", "accept-language", "x-", "x-bad name", ""],
)
def test_non_x_or_malformed_names_are_rejected(name):
    with pytest.raises(ValidationError, match="only X-\\* header names"):
        _rest(forwarded_headers=[name])


@pytest.mark.parametrize("name", ["*", "x-*", "X-Tenant-*"])
def test_wildcards_are_rejected(name):
    with pytest.raises(ValidationError, match="wildcards are not supported"):
        _rest(forwarded_headers=[name])


@pytest.mark.parametrize(
    "toolset",
    [
        lambda: DeploymentToolSet(name="d", tools=[], forwarded_headers=["X-A"]),
        lambda: DialAppToolSet(name="a", deployment_id="app", forwarded_headers=["X-A"]),
        lambda: DialMCPToolSet(deployment_id="mcp", forwarded_headers=["X-A"]),
        lambda: MCPToolSet(
            name="m",
            mcp_server_info=MCPServerInfo(url="https://srv", protocol=MCPProtocol.streamable_http),
            forwarded_headers=["X-A"],
        ),
        lambda: _rest(forwarded_headers=["X-A"]),
    ],
)
def test_every_forwarding_toolset_type_accepts_the_field(toolset):
    assert toolset().forwarded_headers == ["x-a"]
