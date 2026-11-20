import logging

import pytest

from quickapp.common.dial_settings import DialSettings
from quickapp.config.toolsets.deployment import DeploymentToolSet
from quickapp.config.toolsets.dial_app import DialAppToolSet
from quickapp.config.toolsets.dial_mcp import DialMCPToolSet
from quickapp.config.toolsets.mcp import MCPProtocol, MCPServerInfo, MCPToolSet
from quickapp.config.toolsets.rest_api import RestApiToolSet
from quickapp.shared.forwarded_headers._forwarded_headers_settings import ForwardedHeadersSettings
from quickapp.shared.forwarded_headers.forwarded_headers_policy import ForwardedHeadersPolicy

HEADERS = {
    "X-Tenant-Id": "tenant-1",
    "x-project-id": "projects/bucket/p1",
    "X-Timezone": "Europe/Warsaw",
}


@pytest.fixture(autouse=True)
def _reset_reported_drops():
    ForwardedHeadersPolicy._reported_drops.clear()


def _policy(headers=HEADERS, forward_all_to_external=False) -> ForwardedHeadersPolicy:
    return ForwardedHeadersPolicy(
        forwarded_headers=headers,
        settings=ForwardedHeadersSettings(
            FORWARD_ALL_X_HEADERS_TO_EXTERNAL_TOOLSETS=forward_all_to_external
        ),
        dial_settings=DialSettings(url="https://dial.corp"),
    )


def _rest(**kwargs) -> RestApiToolSet:
    return RestApiToolSet(name="billing", tools=[], **kwargs)


def _mcp(url: str, **kwargs) -> MCPToolSet:
    return MCPToolSet(
        name="mcp",
        mcp_server_info=MCPServerInfo(url=url, protocol=MCPProtocol.streamable_http),
        **kwargs,
    )


def _deployment(**kwargs) -> DeploymentToolSet:
    return DeploymentToolSet(name="agents", tools=[], **kwargs)


def test_all_returns_every_header():
    assert _policy().all() == HEADERS


@pytest.mark.parametrize(
    "toolset",
    [
        _deployment(),
        DialAppToolSet(name="app", deployment_id="app"),
        DialMCPToolSet(deployment_id="mcp"),
        _mcp("https://dial.corp/v1/deployments/app/mcp"),
        _mcp("https://DIAL.corp:443/mcp"),
    ],
)
def test_internal_toolset_without_setting_gets_every_header(toolset):
    assert _policy().for_toolset(toolset) == HEADERS


@pytest.mark.parametrize(
    "toolset",
    [
        _rest(),
        _mcp("https://search.example.com/mcp"),
        _mcp("https://dial.corp.attacker.io/mcp"),
    ],
)
def test_external_toolset_without_setting_gets_nothing(toolset):
    assert _policy().for_toolset(toolset) is None


def test_listed_names_are_matched_case_insensitively_and_keep_incoming_casing():
    toolset = _rest(forwarded_headers=["x-tenant-id", "X-PROJECT-ID"])

    assert _policy().for_toolset(toolset) == {
        "X-Tenant-Id": "tenant-1",
        "x-project-id": "projects/bucket/p1",
    }


def test_listed_name_missing_from_the_request_is_not_sent():
    assert _policy().for_toolset(_rest(forwarded_headers=["x-unknown"])) is None


def test_empty_list_sends_nothing_even_to_an_internal_toolset():
    assert _policy().for_toolset(_deployment(forwarded_headers=[])) is None


def test_list_narrows_an_internal_toolset():
    toolset = _deployment(forwarded_headers=["x-tenant-id"])

    assert _policy().for_toolset(toolset) == {"X-Tenant-Id": "tenant-1"}


def test_list_on_a_dial_origin_mcp_narrows_it():
    toolset = _mcp("https://dial.corp/mcp", forwarded_headers=["x-timezone"])

    assert _policy().for_toolset(toolset) == {"X-Timezone": "Europe/Warsaw"}


def test_request_without_x_headers_yields_nothing():
    assert _policy(headers=None).for_toolset(_rest(forwarded_headers=["x-tenant-id"])) is None
    assert _policy(headers=None).for_toolset(_deployment()) is None


def test_admin_switch_restores_all_headers_for_unset_external_toolsets():
    policy = _policy(forward_all_to_external=True)

    assert policy.for_toolset(_rest()) == HEADERS
    assert policy.for_toolset(_mcp("https://search.example.com/mcp")) == HEADERS


def test_admin_switch_does_not_override_an_explicit_list():
    policy = _policy(forward_all_to_external=True)

    assert policy.for_toolset(_rest(forwarded_headers=["x-tenant-id"])) == {
        "X-Tenant-Id": "tenant-1"
    }
    assert policy.for_toolset(_rest(forwarded_headers=[])) is None


def test_dropped_headers_are_logged_by_name_only_and_once(caplog):
    policy = _policy()
    toolset = _rest()

    with caplog.at_level(logging.INFO, logger="quickapp.shared.forwarded_headers"):
        policy.for_toolset(toolset)
        policy.for_toolset(toolset)

    records = [r for r in caplog.records if "billing" in r.getMessage()]
    assert len(records) == 1
    message = records[0].getMessage()
    assert "x-tenant-id" in message and "x-project-id" in message and "x-timezone" in message
    assert "tenant-1" not in message and "projects/bucket/p1" not in message


@pytest.mark.parametrize(
    "toolset",
    [_deployment(), _rest(forwarded_headers=["x-tenant-id"])],
)
def test_nothing_is_logged_when_nothing_is_dropped_by_default(caplog, toolset):
    with caplog.at_level(logging.INFO, logger="quickapp.shared.forwarded_headers"):
        _policy().for_toolset(toolset)

    assert not caplog.records


def test_nothing_is_logged_when_the_request_has_no_x_headers(caplog):
    with caplog.at_level(logging.INFO, logger="quickapp.shared.forwarded_headers"):
        _policy(headers=None).for_toolset(_rest())

    assert not caplog.records
