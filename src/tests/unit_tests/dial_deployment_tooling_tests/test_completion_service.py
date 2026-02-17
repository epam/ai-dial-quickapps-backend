import pytest
from aidial_client.types.chat.request_param import (
    AssistantMessageParam,
    UserMessageParam,
)
from unittest.mock import AsyncMock, MagicMock, call

from quickapp.dial_deployment_tooling.constants import EXTRA_BODY
from quickapp.dial_deployment_tooling.dial_completion_service import DialCompletionService


@pytest.fixture
def dial_client():
    client = MagicMock()
    client.chat.completions.create = AsyncMock()
    client.metadata = MagicMock()

    async def mock_stream():
        chunk = MagicMock()
        chunk.choices = [MagicMock()]
        chunk.choices[0].delta = MagicMock()
        chunk.choices[0].delta.content = "Test response"
        chunk.choices[0].delta.custom_content = None
        yield chunk

    client.chat.completions.create.return_value = mock_stream()
    return client


@pytest.fixture
def completion_service(dial_client):
    return DialCompletionService(dial_client)


@pytest.fixture
def mock_stage_wrapper():
    stage_wrapper = MagicMock()
    stage_wrapper.append_stage_content = MagicMock()
    stage_wrapper.add_stage_attachment = MagicMock()
    return stage_wrapper


@pytest.mark.asyncio
async def test_history_propagation_enabled(completion_service, dial_client, mock_stage_wrapper):
    # Act — pass pre-built history directly
    history = [
        UserMessageParam(role="user", content="First question"),
        AssistantMessageParam(role="assistant", content="First answer"),
        UserMessageParam(role="user", content="Second question"),
        AssistantMessageParam(role="assistant", content="Second answer"),
    ]
    await completion_service.complete_request_async(
        params={"query": "Test query"},
        deployment_id="test-deployment",
        deployment_name="Test Deployment",
        stage_wrapper=mock_stage_wrapper,
        history=history,
    )

    # Assert — 4 history messages + current query
    call_args = dial_client.chat.completions.create.call_args[1]
    assert len(call_args["messages"]) == 5
    assert call_args["messages"][0]["content"] == "First question"
    assert call_args["messages"][0]["role"] == "user"
    assert call_args["messages"][1]["content"] == "First answer"
    assert call_args["messages"][1]["role"] == "assistant"
    assert call_args["messages"][2]["content"] == "Second question"
    assert call_args["messages"][2]["role"] == "user"
    assert call_args["messages"][3]["content"] == "Second answer"
    assert call_args["messages"][3]["role"] == "assistant"
    assert call_args["messages"][4]["content"] == "Test query"
    assert call_args["messages"][4]["role"] == "user"


@pytest.mark.asyncio
async def test_no_history(completion_service, dial_client, mock_stage_wrapper):
    # Act — no history passed
    await completion_service.complete_request_async(
        params={"query": "Test query"},
        deployment_id="test-deployment",
        deployment_name="Test Deployment",
        stage_wrapper=mock_stage_wrapper,
    )

    # Assert — only current query
    call_args = dial_client.chat.completions.create.call_args[1]
    assert len(call_args["messages"]) == 1
    assert call_args["messages"][0]["content"] == "Test query"


@pytest.mark.asyncio
async def test_empty_history(completion_service, dial_client, mock_stage_wrapper):
    # Act — empty history list
    await completion_service.complete_request_async(
        params={"query": "Test query"},
        deployment_id="test-deployment",
        deployment_name="Test Deployment",
        stage_wrapper=mock_stage_wrapper,
        history=[],
    )

    # Assert — only current query
    call_args = dial_client.chat.completions.create.call_args[1]
    assert len(call_args["messages"]) == 1
    assert call_args["messages"][0]["content"] == "Test query"


@pytest.mark.asyncio
async def test_history_none_explicitly(completion_service, dial_client, mock_stage_wrapper):
    # Act — explicitly pass None
    await completion_service.complete_request_async(
        params={"query": "Test query"},
        deployment_id="test-deployment",
        deployment_name="Test Deployment",
        stage_wrapper=mock_stage_wrapper,
        history=None,
    )

    # Assert — only current query
    call_args = dial_client.chat.completions.create.call_args[1]
    assert len(call_args["messages"]) == 1
    assert call_args["messages"][0]["content"] == "Test query"


@pytest.mark.asyncio
async def test_stage_wrapper_none(completion_service, dial_client):
    result = await completion_service.complete_request_async(
        params={"query": "Test query"},
        deployment_id="test-deployment",
        deployment_name="Test Deployment",
        stage_wrapper=None,
    )

    # Assert
    assert result.content == "Test response"
    assert result.content_type == "text/markdown"


@pytest.mark.asyncio
async def test_stage_wrapper_content_streaming(completion_service, dial_client, mock_stage_wrapper):
    # Act
    await completion_service.complete_request_async(
        params={"query": "Test query"},
        deployment_id="test-deployment",
        deployment_name="Test Deployment",
        stage_wrapper=mock_stage_wrapper,
    )

    # Assert - Check that both calls were made: first the header, then the content
    expected_calls = [
        call("> #### Response:\n"),
        call("Test response")
    ]
    mock_stage_wrapper.append_stage_content.assert_has_calls(expected_calls)


@pytest.mark.asyncio
async def test_extra_params_go_to_extra_body_not_top_level(
    completion_service, dial_client, mock_stage_wrapper
):
    """Params other than query and attachment_urls must be in extra_body, not top-level."""
    await completion_service.complete_request_async(
        params={
            "query": "Test query",
            "attachment_urls": ["file/123"],
            "temperature": 0.7,
            "max_tokens": 100,
            "custom_key": "custom_value",
        },
        deployment_id="test-deployment",
        deployment_name="Test Deployment",
        stage_wrapper=mock_stage_wrapper,
    )

    call_args = dial_client.chat.completions.create.call_args[1]
    # Only deployment_name, stream, messages (and extra_body) at top level
    assert set(call_args.keys()) == {"deployment_name", "stream", "messages", EXTRA_BODY}
    assert call_args["messages"][0]["content"] == "Test query"

    extra_body = call_args[EXTRA_BODY]
    assert extra_body["temperature"] == 0.7
    assert extra_body["max_tokens"] == 100
    assert extra_body["custom_key"] == "custom_value"
    # query and attachment_urls must not be in extra_body
    assert "query" not in extra_body
    assert "attachment_urls" not in extra_body


@pytest.mark.asyncio
async def test_extra_body_from_params_merged_with_other_params(
    completion_service, dial_client, mock_stage_wrapper
):
    """If params already contain extra_body (e.g. from deployment), it is merged with other params."""
    await completion_service.complete_request_async(
        params={
            "query": "Test query",
            EXTRA_BODY: {"custom_fields": {"key": "from_deployment"}},
            "temperature": 0.5,
        },
        deployment_id="test-deployment",
        deployment_name="Test Deployment",
        stage_wrapper=mock_stage_wrapper,
    )

    call_args = dial_client.chat.completions.create.call_args[1]
    extra_body = call_args[EXTRA_BODY]
    assert extra_body["custom_fields"] == {"key": "from_deployment"}
    assert extra_body["temperature"] == 0.5
    assert "query" not in extra_body
