from unittest.mock import AsyncMock, MagicMock

import openai
import pytest

from quickapp.tool_discovery._anonymous_agent import _AnonymousAgent


def _make_config(
    tool_discovery=None, service_model=None, orchestrator_deployment_id="orchestrator-model"
):
    config = MagicMock()
    config.orchestrator.deployment.deployment_id = orchestrator_deployment_id
    if tool_discovery is None:
        config.orchestrator.tool_discovery = None
    else:
        discovery = MagicMock()
        discovery.service_model = service_model
        config.orchestrator.tool_discovery = discovery
    return config


def _make_response(content: str):
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.content = content
    return response


CATALOG = [{"name": "tool_a", "description": "Does A"}, {"name": "tool_b", "description": "Does B"}]


@pytest.mark.asyncio
async def test_route_returns_empty_list_for_empty_catalog():
    client = AsyncMock()
    agent = _AnonymousAgent(client=client, config=_make_config())

    result = await agent.route("find a tool", [])

    assert result == []
    client.chat.completions.create.assert_not_called()


@pytest.mark.asyncio
async def test_route_fails_open_when_tool_discovery_is_none():
    client = AsyncMock()
    agent = _AnonymousAgent(client=client, config=_make_config(tool_discovery=None))

    result = await agent.route("find a tool", CATALOG)

    assert result == []
    client.chat.completions.create.assert_not_called()


@pytest.mark.asyncio
async def test_route_returns_matched_names_on_valid_json_response():
    client = AsyncMock()
    client.chat.completions.create.return_value = _make_response('["tool_a", "tool_b"]')
    agent = _AnonymousAgent(client=client, config=_make_config(tool_discovery=True))

    result = await agent.route("find a tool", CATALOG)

    assert result == ["tool_a", "tool_b"]


@pytest.mark.asyncio
async def test_route_uses_service_model_when_configured():
    client = AsyncMock()
    client.chat.completions.create.return_value = _make_response("[]")
    agent = _AnonymousAgent(
        client=client, config=_make_config(tool_discovery=True, service_model="cheap-router-model")
    )

    await agent.route("find a tool", CATALOG)

    assert client.chat.completions.create.call_args.kwargs["model"] == "cheap-router-model"


@pytest.mark.asyncio
async def test_route_falls_back_to_orchestrator_deployment_when_service_model_unset():
    client = AsyncMock()
    client.chat.completions.create.return_value = _make_response("[]")
    agent = _AnonymousAgent(
        client=client,
        config=_make_config(
            tool_discovery=True, service_model=None, orchestrator_deployment_id="orchestrator-model"
        ),
    )

    await agent.route("find a tool", CATALOG)

    assert client.chat.completions.create.call_args.kwargs["model"] == "orchestrator-model"


@pytest.mark.asyncio
async def test_route_returns_empty_list_on_non_json_response():
    client = AsyncMock()
    client.chat.completions.create.return_value = _make_response("not json at all")
    agent = _AnonymousAgent(client=client, config=_make_config(tool_discovery=True))

    result = await agent.route("find a tool", CATALOG)

    assert result == []


@pytest.mark.asyncio
async def test_route_filters_out_non_string_entries_from_response():
    client = AsyncMock()
    client.chat.completions.create.return_value = _make_response('["tool_a", 123, null]')
    agent = _AnonymousAgent(client=client, config=_make_config(tool_discovery=True))

    result = await agent.route("find a tool", CATALOG)

    assert result == ["tool_a"]


@pytest.mark.asyncio
async def test_route_returns_empty_list_on_openai_error():
    client = AsyncMock()
    client.chat.completions.create.side_effect = openai.APIConnectionError(request=MagicMock())
    agent = _AnonymousAgent(client=client, config=_make_config(tool_discovery=True))

    result = await agent.route("find a tool", CATALOG)

    assert result == []
