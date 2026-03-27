from unittest.mock import AsyncMock, MagicMock, call

import pytest
from aidial_client.types.chat.request_param import (
    AssistantMessageParam,
    AttachmentParam,
    CustomContentParam,
    UserMessageParam,
)
from pydantic import SecretStr

from quickapp.common.file_reference_pattern import strip_file_prefix
from quickapp.dial_deployment_tooling.constants import EXTRA_BODY, EXTRA_HEADERS
from quickapp.dial_deployment_tooling.dial_completion_service import DialCompletionService


@pytest.fixture
def azure_client():
    client = MagicMock()
    client.chat.completions.create = AsyncMock()

    async def mock_stream():
        chunk = MagicMock()
        chunk.choices = [MagicMock()]
        chunk.choices[0].delta = MagicMock()
        chunk.choices[0].delta.content = "Test response"
        chunk.choices[0].delta.custom_content = None
        chunk.choices[0].delta.tool_calls = None
        chunk.usage = None
        chunk.model_extra = {}
        yield chunk

    client.chat.completions.create.return_value = mock_stream()
    return client


@pytest.fixture
def completion_service(azure_client):
    dial_settings = MagicMock(url="https://dial.example", api_version="2024-05-01-preview")
    api_key = SecretStr("test-key")
    return DialCompletionService(
        azure_client, dial_settings, api_key, dial_client=None, forwarded_headers=None
    )


@pytest.fixture
def mock_stage_wrapper():
    stage_wrapper = MagicMock()
    stage_wrapper.append_stage_content = MagicMock()
    stage_wrapper.add_attachment = MagicMock()
    return stage_wrapper


@pytest.mark.asyncio
async def test_history_propagation_enabled(completion_service, azure_client, mock_stage_wrapper):
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
    call_args = azure_client.chat.completions.create.call_args[1]
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
async def test_no_history(completion_service, azure_client, mock_stage_wrapper):
    # Act — no history passed
    await completion_service.complete_request_async(
        params={"query": "Test query"},
        deployment_id="test-deployment",
        deployment_name="Test Deployment",
        stage_wrapper=mock_stage_wrapper,
    )

    # Assert — only current query
    call_args = azure_client.chat.completions.create.call_args[1]
    assert len(call_args["messages"]) == 1
    assert call_args["messages"][0]["content"] == "Test query"


@pytest.mark.asyncio
async def test_empty_history(completion_service, azure_client, mock_stage_wrapper):
    # Act — empty history list
    await completion_service.complete_request_async(
        params={"query": "Test query"},
        deployment_id="test-deployment",
        deployment_name="Test Deployment",
        stage_wrapper=mock_stage_wrapper,
        history=[],
    )

    # Assert — only current query
    call_args = azure_client.chat.completions.create.call_args[1]
    assert len(call_args["messages"]) == 1
    assert call_args["messages"][0]["content"] == "Test query"


@pytest.mark.asyncio
async def test_history_none_explicitly(completion_service, azure_client, mock_stage_wrapper):
    # Act — explicitly pass None
    await completion_service.complete_request_async(
        params={"query": "Test query"},
        deployment_id="test-deployment",
        deployment_name="Test Deployment",
        stage_wrapper=mock_stage_wrapper,
        history=None,
    )

    # Assert — only current query
    call_args = azure_client.chat.completions.create.call_args[1]
    assert len(call_args["messages"]) == 1
    assert call_args["messages"][0]["content"] == "Test query"


@pytest.mark.asyncio
async def test_stage_wrapper_none(completion_service, azure_client):
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
async def test_stage_wrapper_content_streaming(
    completion_service, azure_client, mock_stage_wrapper
):
    # Act
    await completion_service.complete_request_async(
        params={"query": "Test query"},
        deployment_id="test-deployment",
        deployment_name="Test Deployment",
        stage_wrapper=mock_stage_wrapper,
    )

    # Assert - Check that both calls were made: first the header, then the content
    expected_calls = [call("> #### Response:\n"), call("Test response")]
    mock_stage_wrapper.append_stage_content.assert_has_calls(expected_calls)


@pytest.mark.asyncio
async def test_extra_params_go_to_extra_body_not_top_level(
    completion_service, azure_client, mock_stage_wrapper
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

    call_args = azure_client.chat.completions.create.call_args[1]
    # Only model, stream, messages (and extra_body) at top level
    assert set(call_args.keys()) == {"model", "stream", "messages", EXTRA_BODY}
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
    completion_service, azure_client, mock_stage_wrapper
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

    call_args = azure_client.chat.completions.create.call_args[1]
    extra_body = call_args[EXTRA_BODY]
    assert extra_body["custom_fields"] == {"key": "from_deployment"}
    assert extra_body["temperature"] == 0.5
    assert "query" not in extra_body


@pytest.mark.asyncio
async def test_history_with_custom_content_passed_through(
    completion_service, azure_client, mock_stage_wrapper
):
    """History entries with custom_content appear unchanged in messages sent to the API."""
    history = [
        UserMessageParam(
            role="user",
            content="Describe the image",
            custom_content=CustomContentParam(
                attachments=[
                    AttachmentParam(type="image/png", title="img.png", url="files/abc/img.png")
                ]
            ),
        ),
        AssistantMessageParam(
            role="assistant",
            content="It shows a chart",
            custom_content=CustomContentParam(
                attachments=[
                    AttachmentParam(type="image/png", title="annotated.png", url="files/out.png")
                ],
                state={"cursor": 10},
            ),
        ),
    ]
    await completion_service.complete_request_async(
        params={"query": "Follow up question"},
        deployment_id="test-deployment",
        deployment_name="Test Deployment",
        stage_wrapper=mock_stage_wrapper,
        history=history,
    )

    call_args = azure_client.chat.completions.create.call_args[1]
    msgs = call_args["messages"]
    assert len(msgs) == 3

    # User history message preserves custom_content
    user_msg = msgs[0]
    assert user_msg["content"] == "Describe the image"
    assert user_msg["custom_content"]["attachments"][0]["type"] == "image/png"
    assert user_msg["custom_content"]["attachments"][0]["url"] == "files/abc/img.png"

    # Assistant history message preserves custom_content
    assistant_msg = msgs[1]
    assert assistant_msg["content"] == "It shows a chart"
    assert assistant_msg["custom_content"]["attachments"][0]["title"] == "annotated.png"
    assert assistant_msg["custom_content"]["state"] == {"cursor": 10}

    # Current query is the last message
    assert msgs[2]["content"] == "Follow up question"
    assert msgs[2]["role"] == "user"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "file_relative_url",
    [
        "file:base64::files/images/chart.png",
        "files/images/chart.png",
    ],
)
async def test_resolve_attachment_queries_dial_client_metadata(file_relative_url):
    """``_resolve_attachment`` calls ``dial_client.metadata.get('files', stripped_path)``."""
    fileinfo = MagicMock()
    fileinfo.content_type = "image/png"
    fileinfo.name = "photo.png"
    fileinfo.url = "files/resolved.png"

    metadata = MagicMock()
    metadata.get = AsyncMock(return_value=fileinfo)

    dial_client = MagicMock()
    dial_client.metadata = metadata

    dial_settings = MagicMock(url="https://dial.example", api_version="2024-05-01-preview")
    service = DialCompletionService(
        MagicMock(),
        dial_settings,
        SecretStr("test-key"),
        dial_client=dial_client,
        forwarded_headers=None,
    )
    result = await service._resolve_attachment(file_relative_url)

    metadata.get.assert_called_once_with("files", strip_file_prefix(file_relative_url))
    assert result == AttachmentParam(type="image/png", title="photo.png", url="files/resolved.png")


@pytest.mark.asyncio
async def test_forwarded_x_headers_passed_to_chat_completion(azure_client, mock_stage_wrapper):
    """X-* headers from forwarded_headers (dict) are sent as extra_headers to chat completions."""
    forwarded = {"X-Request-Id": "deploy-req-789", "X-Deployment-Custom": "deploy-val"}
    dial_settings = MagicMock(url="https://dial.example", api_version="2024-05-01-preview")
    service = DialCompletionService(
        azure_client,
        dial_settings,
        SecretStr("test-key"),
        dial_client=None,
        forwarded_headers=forwarded,
    )

    await service.complete_request_async(
        params={"query": "Test query"},
        deployment_id="test-deployment",
        deployment_name="Test Deployment",
        stage_wrapper=mock_stage_wrapper,
    )

    call_args = azure_client.chat.completions.create.call_args[1]
    assert EXTRA_HEADERS in call_args
    extra_headers = call_args[EXTRA_HEADERS]
    assert extra_headers["X-Request-Id"] == "deploy-req-789"
    assert extra_headers["X-Deployment-Custom"] == "deploy-val"


@pytest.mark.asyncio
async def test_custom_fields_configuration_routed_to_extra_body(
    completion_service, azure_client, mock_stage_wrapper
):
    """Pre-wrapped custom_fields.configuration appears correctly nested in extra_body."""
    await completion_service.complete_request_async(
        params={
            "query": "Test query",
            "temperature": 0.7,
            "custom_fields": {"configuration": {"size": "1024x1024", "quality": "high"}},
        },
        deployment_id="test-deployment",
        deployment_name="Test Deployment",
        stage_wrapper=mock_stage_wrapper,
    )

    call_args = azure_client.chat.completions.create.call_args[1]
    extra_body = call_args[EXTRA_BODY]
    assert extra_body["temperature"] == 0.7
    assert extra_body["custom_fields"] == {
        "configuration": {"size": "1024x1024", "quality": "high"}
    }
    assert "query" not in extra_body
