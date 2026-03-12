import pytest
from aidial_client.types.chat.request_param import (
    AssistantMessageParam,
    AttachmentParam,
    CustomContentParam,
    UserMessageParam,
)
from unittest.mock import AsyncMock, MagicMock, call

from quickapp.common import ForwardedHeaders
from quickapp.dial_deployment_tooling.constants import EXTRA_BODY, EXTRA_HEADERS
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
    return DialCompletionService(dial_client, None)


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


@pytest.mark.asyncio
async def test_history_with_custom_content_passed_through(
    completion_service, dial_client, mock_stage_wrapper
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

    call_args = dial_client.chat.completions.create.call_args[1]
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
    "file_relative_url, expected_stripped_url",
    [
        # base64:: prefix — binary/encoded content
        ("file:base64::files/images/chart.png", "files/images/chart.png"),
        # text:: prefix — plain-text content
        ("file:text::files/code/main.py", "files/code/main.py"),
        # url:: prefix — bare URL pass-through (lowercase)
        ("file:url::files/docs/report.pdf", "files/docs/report.pdf"),
        # url:: prefix — case-insensitive match per the convention
        ("file:URL::files/abc/photo.png", "files/abc/photo.png"),
        # bare file: with no type prefix — still strips the file: marker
        ("file:files/abc/photo.png", "files/abc/photo.png"),
    ],
)
async def test_resolve_attachment_strips_file_prefix(dial_client, file_relative_url, expected_stripped_url):
    """_resolve_attachment must strip any file:{prefix}:: marker before querying metadata."""
    fileinfo = MagicMock()
    fileinfo.content_type = "image/png"
    fileinfo.name = "photo.png"
    fileinfo.url = expected_stripped_url
    dial_client.metadata.get = AsyncMock(return_value=fileinfo)

    service = DialCompletionService(dial_client, None)
    result = await service._resolve_attachment(file_relative_url)

    dial_client.metadata.get.assert_called_once_with("files", expected_stripped_url)
    assert result == AttachmentParam(type="image/png", title="photo.png", url=expected_stripped_url)


@pytest.mark.asyncio
async def test_resolve_attachment_without_prefix(dial_client):
    """_resolve_attachment must pass the URL unchanged when there is no file: prefix."""
    fileinfo = MagicMock()
    fileinfo.content_type = "application/pdf"
    fileinfo.name = "report.pdf"
    fileinfo.url = "files/xyz/report.pdf"
    dial_client.metadata.get = AsyncMock(return_value=fileinfo)

    service = DialCompletionService(dial_client, None)
    result = await service._resolve_attachment("files/xyz/report.pdf")

    dial_client.metadata.get.assert_called_once_with("files", "files/xyz/report.pdf")
    assert result == AttachmentParam(type="application/pdf", title="report.pdf", url="files/xyz/report.pdf")


@pytest.mark.asyncio
async def test_forwarded_x_headers_passed_to_chat_completion(dial_client, mock_stage_wrapper):
    """X-* headers from forwarded_headers (dict) are sent as extra_headers to chat completions."""
    forwarded = {"X-Request-Id": "deploy-req-789", "X-Deployment-Custom": "deploy-val"}
    service = DialCompletionService(dial_client, forwarded)

    await service.complete_request_async(
        params={"query": "Test query"},
        deployment_id="test-deployment",
        deployment_name="Test Deployment",
        stage_wrapper=mock_stage_wrapper,
    )

    call_args = dial_client.chat.completions.create.call_args[1]
    assert EXTRA_HEADERS in call_args
    extra_headers = call_args[EXTRA_HEADERS]
    assert extra_headers["X-Request-Id"] == "deploy-req-789"
    assert extra_headers["X-Deployment-Custom"] == "deploy-val"


# --- Stage propagation: _consume_stream with delta.custom_content.stages ---


async def _stream_with_stages(stages_payload: list, main_content: str = "Main"):
    """Yield chunks: one with content, one with custom_content.stages."""
    chunk1 = MagicMock()
    chunk1.choices = [MagicMock()]
    chunk1.choices[0].delta = MagicMock()
    chunk1.choices[0].delta.content = main_content
    chunk1.choices[0].delta.custom_content = None
    chunk1.usage = None
    chunk1.model_extra = {}
    yield chunk1

    chunk2 = MagicMock()
    chunk2.choices = [MagicMock()]
    chunk2.choices[0].delta = MagicMock()
    chunk2.choices[0].delta.content = None
    cc = MagicMock()
    cc.attachments = None
    cc.state = None
    cc.stages = stages_payload
    chunk2.choices[0].delta.custom_content = cc
    chunk2.usage = None
    chunk2.model_extra = {}
    yield chunk2


@pytest.mark.asyncio
async def test_consume_stream_propagates_stages_with_prefixed_names(
    completion_service, dial_client, mock_stage_wrapper
):
    """With propagate_stages=True and stream containing delta.custom_content.stages, stages are created with prefixed names and content."""
    stages = [
        {"name": "Step 1", "content": "First step content"},
        {"name": "Step 2", "content": "Second step content"},
    ]
    dial_client.chat.completions.create.return_value = _stream_with_stages(stages)
    mock_stage_wrapper.create_propagated_stage = MagicMock()

    await completion_service.complete_request_async(
        params={"query": "Test"},
        deployment_id="dep",
        deployment_name="Dep",
        stage_wrapper=mock_stage_wrapper,
        propagate_stages=True,
        tool_stage_display_name="Call RAG:",
    )

    assert mock_stage_wrapper.create_propagated_stage.call_count == 2
    calls = mock_stage_wrapper.create_propagated_stage.call_args_list
    assert calls[0][0][0] == "Call RAG: › Step 1"
    assert calls[0][0][1] == "First step content"
    assert calls[1][0][0] == "Call RAG: › Step 2"
    assert calls[1][0][1] == "Second step content"


@pytest.mark.asyncio
async def test_consume_stream_no_propagation_when_propagate_stages_false(
    completion_service, dial_client, mock_stage_wrapper
):
    """With propagate_stages=False, create_propagated_stage is not called even if stream has stages."""
    stages = [{"name": "Step 1", "content": "x"}]
    dial_client.chat.completions.create.return_value = _stream_with_stages(stages)
    mock_stage_wrapper.create_propagated_stage = MagicMock()

    await completion_service.complete_request_async(
        params={"query": "Test"},
        deployment_id="dep",
        deployment_name="Dep",
        stage_wrapper=mock_stage_wrapper,
        propagate_stages=False,
        tool_stage_display_name="Call RAG:",
    )

    mock_stage_wrapper.create_propagated_stage.assert_not_called()


@pytest.mark.asyncio
async def test_consume_stream_stage_propagation_writes_attachments(
    completion_service, dial_client, mock_stage_wrapper
):
    """Subagent stage with attachments: create_propagated_stage receives attachments list."""
    stages = [
        {
            "name": "Result",
            "content": "Done",
            "attachments": [{"type": "image/png", "title": "out.png", "url": "files/out.png"}],
        },
    ]
    dial_client.chat.completions.create.return_value = _stream_with_stages(stages)
    mock_stage_wrapper.create_propagated_stage = MagicMock()

    await completion_service.complete_request_async(
        params={"query": "Test"},
        deployment_id="dep",
        deployment_name="Dep",
        stage_wrapper=mock_stage_wrapper,
        propagate_stages=True,
        tool_stage_display_name="Tool:",
    )

    mock_stage_wrapper.create_propagated_stage.assert_called_once()
    call_args = mock_stage_wrapper.create_propagated_stage.call_args[0]
    assert call_args[0] == "Tool: › Result"
    assert call_args[1] == "Done"
    assert len(call_args[2]) == 1
    assert call_args[2][0].type == "image/png"
    assert call_args[2][0].title == "out.png"


# --- Stage propagation error handling: malformed stages or create_propagated_stage failure ---


@pytest.mark.asyncio
async def test_consume_stream_malformed_stages_does_not_fail_completion(
    completion_service, dial_client, mock_stage_wrapper
):
    """Malformed custom_content.stages (non-dict items) are skipped; completion returns and valid stages still propagated."""
    stages = [
        {"name": "Valid", "content": "ok"},
        None,
        "not a dict",
        {"name": "Also valid", "content": "yes"},
    ]
    dial_client.chat.completions.create.return_value = _stream_with_stages(stages)
    mock_stage_wrapper.create_propagated_stage = MagicMock()

    result = await completion_service.complete_request_async(
        params={"query": "Test"},
        deployment_id="dep",
        deployment_name="Dep",
        stage_wrapper=mock_stage_wrapper,
        propagate_stages=True,
        tool_stage_display_name="App:",
    )

    assert result.content == "Main"
    assert mock_stage_wrapper.create_propagated_stage.call_count == 2
    calls = mock_stage_wrapper.create_propagated_stage.call_args_list
    names = [c[0][0] for c in calls]
    assert "App: › Valid" in names
    assert "App: › Also valid" in names


@pytest.mark.asyncio
async def test_consume_stream_create_propagated_stage_failure_falls_back(
    completion_service, dial_client, mock_stage_wrapper
):
    """When create_propagated_stage raises, completion does not fail; fallback content is appended to stage."""
    stages = [{"name": "Step 1", "content": "one"}, {"name": "Step 2", "content": "two"}]
    dial_client.chat.completions.create.return_value = _stream_with_stages(stages)
    mock_stage_wrapper.create_propagated_stage = MagicMock(side_effect=RuntimeError("SDK error"))

    result = await completion_service.complete_request_async(
        params={"query": "Test"},
        deployment_id="dep",
        deployment_name="Dep",
        stage_wrapper=mock_stage_wrapper,
        propagate_stages=True,
        tool_stage_display_name="Call RAG:",
    )

    assert result.content == "Main"
    # Fallback: append_stage_content called with "Subagent stages" header and prefixed stage content
    append_calls = [c[0][0] for c in mock_stage_wrapper.append_stage_content.call_args_list]
    full_append = " ".join(str(c) for c in append_calls)
    assert "Subagent stages" in full_append
    assert "**Call RAG: › Step 1**" in full_append
    assert "**Call RAG: › Step 2**" in full_append
