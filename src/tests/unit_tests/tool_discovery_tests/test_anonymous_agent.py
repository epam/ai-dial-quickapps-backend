import json
from unittest.mock import AsyncMock, MagicMock

import openai
import pytest
from injector import Binder, Injector
from openai.types import CompletionUsage

from quickapp.common import DEPLOYMENT_AZURE_CLIENT, ORCHESTRATOR_AZURE_CLIENT
from quickapp.common.deferred_tool_types import DeferredToolCatalogEntry
from quickapp.common.deployment_usage import ModelUsage
from quickapp.config.application import ApplicationConfig
from quickapp.tool_discovery._anonymous_agent import _AnonymousAgent


def _make_config(tool_discovery=None, service_model="service-model"):
    config = MagicMock()
    if tool_discovery is None:
        config.orchestrator.tool_discovery = None
    else:
        discovery = MagicMock()
        discovery.service_model = service_model
        config.orchestrator.tool_discovery = discovery
    return config


def _answer(*names: str) -> str:
    return json.dumps({"matches": [{"name": name, "score": 1} for name in names]})


def _make_response(content: str, usage: CompletionUsage | None = None):
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.content = content
    response.usage = usage
    return response


CATALOG: list[DeferredToolCatalogEntry] = [
    {"name": "tool_a", "description": "Does A", "toolset": "ts"},
    {"name": "tool_b", "description": "Does B", "toolset": "ts"},
]


async def _route(agent: _AnonymousAgent, catalog):
    return await agent.route("find a tool", catalog, kind="tool", limit=10, threshold=0.0)


@pytest.mark.asyncio
async def test_route_returns_empty_list_for_empty_catalog():
    client = AsyncMock()
    agent = _AnonymousAgent(client, _make_config())

    result = await _route(agent, [])

    assert result.names == []
    client.chat.completions.create.assert_not_called()


@pytest.mark.asyncio
async def test_route_fails_open_when_tool_discovery_is_none():
    client = AsyncMock()
    agent = _AnonymousAgent(client, _make_config(tool_discovery=None))

    result = await _route(agent, CATALOG)

    assert result.names == []
    client.chat.completions.create.assert_not_called()


@pytest.mark.asyncio
async def test_route_returns_matched_names_on_valid_json_response():
    client = AsyncMock()
    client.chat.completions.create.return_value = _make_response(_answer("tool_a", "tool_b"))
    agent = _AnonymousAgent(client, _make_config(tool_discovery=True))

    result = await _route(agent, CATALOG)

    assert result.names == ["tool_a", "tool_b"]


@pytest.mark.asyncio
async def test_route_uses_service_model_when_configured():
    client = AsyncMock()
    client.chat.completions.create.return_value = _make_response(_answer())
    agent = _AnonymousAgent(
        client, _make_config(tool_discovery=True, service_model="cheap-router-model")
    )

    await _route(agent, CATALOG)

    assert client.chat.completions.create.call_args.kwargs["model"] == "cheap-router-model"


@pytest.mark.asyncio
async def test_route_returns_empty_list_on_non_json_response():
    client = AsyncMock()
    client.chat.completions.create.return_value = _make_response("not json at all")
    agent = _AnonymousAgent(client, _make_config(tool_discovery=True))

    result = await _route(agent, CATALOG)

    assert result.names == []


@pytest.mark.asyncio
async def test_route_returns_empty_list_on_answer_not_matching_the_schema():
    client = AsyncMock()
    client.chat.completions.create.return_value = _make_response('{"matches": ["tool_a"]}')
    agent = _AnonymousAgent(client, _make_config(tool_discovery=True))

    result = await _route(agent, CATALOG)

    assert result.names == []


@pytest.mark.asyncio
async def test_route_returns_empty_list_on_openai_error():
    client = AsyncMock()
    client.chat.completions.create.side_effect = openai.APIConnectionError(request=MagicMock())
    agent = _AnonymousAgent(client, _make_config(tool_discovery=True))

    result = await _route(agent, CATALOG)

    assert result.names == []


_USAGE = CompletionUsage(prompt_tokens=120, completion_tokens=8, total_tokens=128)


@pytest.mark.asyncio
async def test_route_returns_usage_of_the_routing_call():
    client = AsyncMock()
    client.chat.completions.create.return_value = _make_response(_answer("tool_a"), _USAGE)
    agent = _AnonymousAgent(
        client, _make_config(tool_discovery=True, service_model="cheap-router-model")
    )

    result = await _route(agent, CATALOG)

    assert result.usage == ModelUsage(
        model="cheap-router-model", prompt_tokens=120, completion_tokens=8
    )


@pytest.mark.asyncio
async def test_route_returns_usage_on_non_json_response():
    client = AsyncMock()
    client.chat.completions.create.return_value = _make_response("not json", _USAGE)
    agent = _AnonymousAgent(client, _make_config(tool_discovery=True))

    result = await _route(agent, CATALOG)

    assert result.names == []
    assert result.usage == ModelUsage(model="service-model", prompt_tokens=120, completion_tokens=8)


@pytest.mark.asyncio
async def test_route_returns_no_usage_on_openai_error():
    client = AsyncMock()
    client.chat.completions.create.side_effect = openai.APIConnectionError(request=MagicMock())
    agent = _AnonymousAgent(client, _make_config(tool_discovery=True))

    result = await _route(agent, CATALOG)

    assert result.usage is None


@pytest.mark.asyncio
async def test_route_uses_deployment_client_not_orchestrator_client():
    deployment_client, orchestrator_client = AsyncMock(), AsyncMock()
    deployment_client.chat.completions.create.return_value = _make_response(_answer("tool_a"))

    def configure(binder: Binder) -> None:
        binder.bind(DEPLOYMENT_AZURE_CLIENT, to=deployment_client)
        binder.bind(ORCHESTRATOR_AZURE_CLIENT, to=orchestrator_client)
        binder.bind(ApplicationConfig, to=_make_config(tool_discovery=True))

    agent = Injector([configure]).get(_AnonymousAgent)

    result = await _route(agent, CATALOG)

    assert result.names == ["tool_a"]
    deployment_client.chat.completions.create.assert_awaited_once()
    orchestrator_client.chat.completions.create.assert_not_called()


@pytest.mark.asyncio
async def test_route_fails_open_when_response_has_no_choices():
    client = AsyncMock()
    response = _make_response("", _USAGE)
    response.choices = []
    client.chat.completions.create.return_value = response
    agent = _AnonymousAgent(client, _make_config(tool_discovery=True))

    result = await _route(agent, CATALOG)

    assert result.names == []
    assert result.usage == ModelUsage(model="service-model", prompt_tokens=120, completion_tokens=8)


def _bad_request() -> openai.BadRequestError:
    response = MagicMock()
    response.status_code = 400
    response.headers = {}
    return openai.BadRequestError(
        "unsupported", response=response, body={"error": {"message": "unsupported"}}
    )


@pytest.mark.asyncio
async def test_route_always_requests_structured_output():
    client = AsyncMock()
    client.chat.completions.create.return_value = _make_response(
        '{"matches": [{"name": "tool_b", "score": 0.9}]}'
    )
    agent = _AnonymousAgent(client, _make_config(tool_discovery=True))

    result = await _route(agent, CATALOG)

    assert result.names == ["tool_b"]
    schema = client.chat.completions.create.call_args.kwargs["response_format"]["json_schema"]
    assert schema["strict"] is True
    name_schema = schema["schema"]["properties"]["matches"]["items"]["properties"]["name"]
    assert name_schema == {"title": "Name", "type": "string"}


@pytest.mark.asyncio
async def test_route_makes_a_single_call_and_yields_nothing_on_bad_request():
    client = AsyncMock()
    client.chat.completions.create.side_effect = _bad_request()
    agent = _AnonymousAgent(client, _make_config(tool_discovery=True))

    result = await _route(agent, CATALOG)

    assert result.names == []
    assert result.usage is None
    client.chat.completions.create.assert_awaited_once()


@pytest.mark.asyncio
async def test_route_returns_warning_with_the_actual_error_on_bad_request():
    client = AsyncMock()
    client.chat.completions.create.side_effect = _bad_request()
    agent = _AnonymousAgent(client, _make_config(tool_discovery=True, service_model="m1"))

    result = await _route(agent, CATALOG)

    [warning] = result.warnings
    assert "'m1'" in warning
    assert "unsupported" in warning


@pytest.mark.asyncio
async def test_route_returns_no_warning_on_non_400_error():
    client = AsyncMock()
    client.chat.completions.create.side_effect = openai.APIConnectionError(request=MagicMock())
    agent = _AnonymousAgent(client, _make_config(tool_discovery=True))

    result = await _route(agent, CATALOG)

    assert result.warnings == []
