import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from aidial_sdk.chat_completion import Message, Role
from aidial_sdk.chat_completion.request import (
    Attachment as SdkAttachment,
    CustomContent,
    FunctionCall,
    ToolCall,
)
from pydantic import StrictStr

from quickapp.common import CompletionResult
from quickapp.config.tools.deployment import ContentPropagation
from quickapp.dial_deployment_tooling.base_deployment_tool import BaseDeploymentTool


def _make_tool_call(
    tool_call_id: str,
    name: str,
    query: str,
    attachment_urls: list[str] | None = None,
) -> ToolCall:
    args: dict[str, Any] = {"query": query}
    if attachment_urls is not None:
        args["attachment_urls"] = attachment_urls
    return ToolCall(
        id=tool_call_id,
        type="function",
        function=FunctionCall(name=name, arguments=json.dumps(args)),
    )


def _make_assistant_with_tool_calls(tool_calls: list[ToolCall]) -> Message:
    return Message(
        role=Role.ASSISTANT,
        content=StrictStr(" "),
        tool_calls=tool_calls,
    )


def _make_tool_result(
    tool_call_id: str,
    content: str,
    custom_content: CustomContent | None = None,
) -> Message:
    return Message(
        role=Role.TOOL,
        content=StrictStr(content),
        tool_call_id=tool_call_id,
        custom_content=custom_content,
    )


def _build_tool(
    messages: list[Message],
    dial_completion_service: Any = None,
) -> BaseDeploymentTool:
    """Build a BaseDeploymentTool with minimal mocks for testing _extract_tool_history."""
    if dial_completion_service is None:
        dial_completion_service = MagicMock()
    tool_config = MagicMock()
    tool_config.display = None
    tool_config.attachment = MagicMock()
    tool_config.attachment.supported_types = []
    tool_config.attachment.propagate_types_to_choice = []
    tool_config.fallback_configuration = None
    return BaseDeploymentTool(
        application_id="test-app",
        application_name="Test App",
        tool_config=tool_config,
        content_propagation=None,
        dial_completion_service=dial_completion_service,
        messages=messages,
        perf_timer=MagicMock(),
        stage_wrapper_builder=MagicMock(),
    )


@pytest.mark.asyncio
async def test_extract_single_tool_history():
    """Single tool with two prior interactions extracts correctly."""
    messages: list[Message] = [
        Message(role=Role.USER, content=StrictStr("Help me")),
        _make_assistant_with_tool_calls([
            _make_tool_call("tc1", "my_tool", "First question"),
        ]),
        _make_tool_result("tc1", "First answer"),
        _make_assistant_with_tool_calls([
            _make_tool_call("tc2", "my_tool", "Second question"),
        ]),
        _make_tool_result("tc2", "Second answer"),
    ]

    tool = _build_tool(messages)
    history = await tool._extract_tool_history("my_tool")

    assert len(history) == 4
    assert history[0]["role"] == "user"
    assert history[0]["content"] == "First question"
    assert history[1]["role"] == "assistant"
    assert history[1]["content"] == "First answer"
    assert history[2]["role"] == "user"
    assert history[2]["content"] == "Second question"
    assert history[3]["role"] == "assistant"
    assert history[3]["content"] == "Second answer"


@pytest.mark.asyncio
async def test_extract_filters_by_tool_name():
    """Only interactions for the target tool are included; other tools are excluded."""
    messages: list[Message] = [
        Message(role=Role.USER, content=StrictStr("Start")),
        _make_assistant_with_tool_calls([
            _make_tool_call("tc_a1", "tool_a", "question for A"),
            _make_tool_call("tc_b1", "tool_b", "question for B"),
        ]),
        _make_tool_result("tc_a1", "answer from A"),
        _make_tool_result("tc_b1", "answer from B"),
    ]

    tool = _build_tool(messages)
    history = await tool._extract_tool_history("tool_a")

    assert len(history) == 2
    assert history[0]["content"] == "question for A"
    assert history[1]["content"] == "answer from A"


@pytest.mark.asyncio
async def test_extract_excludes_current_call():
    """Tool call without a TOOL result yet is excluded (current invocation)."""
    messages: list[Message] = [
        Message(role=Role.USER, content=StrictStr("Hello")),
        _make_assistant_with_tool_calls([
            _make_tool_call("tc1", "my_tool", "old question"),
        ]),
        _make_tool_result("tc1", "old answer"),
        # Current call — no TOOL result appended yet
        _make_assistant_with_tool_calls([
            _make_tool_call("tc2", "my_tool", "current question"),
        ]),
    ]

    tool = _build_tool(messages)
    history = await tool._extract_tool_history("my_tool")

    # Only the first completed interaction
    assert len(history) == 2
    assert history[0]["content"] == "old question"
    assert history[1]["content"] == "old answer"


@pytest.mark.asyncio
async def test_extract_live_mutations():
    """Messages appended after list creation are visible (live reference)."""
    messages: list[Message] = [
        Message(role=Role.USER, content=StrictStr("Hello")),
    ]

    # Simulate orchestrator appending messages after list creation
    messages.append(
        _make_assistant_with_tool_calls([
            _make_tool_call("tc_late", "my_tool", "late question"),
        ])
    )
    messages.append(_make_tool_result("tc_late", "late answer"))

    tool = _build_tool(messages)
    history = await tool._extract_tool_history("my_tool")

    assert len(history) == 2
    assert history[0]["content"] == "late question"
    assert history[1]["content"] == "late answer"


@pytest.mark.asyncio
async def test_extract_empty_when_no_matches():
    """No matching tool calls returns empty list."""
    messages: list[Message] = [
        Message(role=Role.USER, content=StrictStr("Hello")),
        _make_assistant_with_tool_calls([
            _make_tool_call("tc1", "other_tool", "question"),
        ]),
        _make_tool_result("tc1", "answer"),
    ]

    tool = _build_tool(messages)
    history = await tool._extract_tool_history("my_tool")

    assert history == []


@pytest.mark.asyncio
async def test_extract_empty_tool_name():
    """Empty tool name returns empty list."""
    messages: list[Message] = [
        Message(role=Role.USER, content=StrictStr("Hello")),
    ]

    tool = _build_tool(messages)
    history = await tool._extract_tool_history("")

    assert history == []


@pytest.mark.asyncio
async def test_extract_preserves_response_attachments():
    """TOOL message with custom_content.attachments → AssistantMessageParam has attachments."""
    sdk_attachment = SdkAttachment(
        type="image/png",
        title="screenshot.png",
        url="files/abc/screenshot.png",
        reference_url="https://example.com/screenshot.png",
        reference_type="storage",
    )
    messages: list[Message] = [
        Message(role=Role.USER, content=StrictStr("Hello")),
        _make_assistant_with_tool_calls([
            _make_tool_call("tc1", "my_tool", "describe image"),
        ]),
        _make_tool_result(
            "tc1",
            "It shows a chart",
            custom_content=CustomContent(attachments=[sdk_attachment]),
        ),
    ]

    tool = _build_tool(messages)
    history = await tool._extract_tool_history("my_tool")

    assert len(history) == 2
    assistant_msg = history[1]
    assert assistant_msg["role"] == "assistant"
    assert assistant_msg["content"] == "It shows a chart"
    cc = assistant_msg["custom_content"]
    assert len(cc["attachments"]) == 1
    att = cc["attachments"][0]
    assert att["type"] == "image/png"
    assert att["title"] == "screenshot.png"
    assert att["url"] == "files/abc/screenshot.png"
    assert att["reference_url"] == "https://example.com/screenshot.png"
    assert att["reference_type"] == "storage"


@pytest.mark.asyncio
async def test_extract_preserves_response_state():
    """TOOL message with custom_content.state → AssistantMessageParam has state."""
    state_data = {"cursor": 42, "mode": "streaming"}
    messages: list[Message] = [
        Message(role=Role.USER, content=StrictStr("Hello")),
        _make_assistant_with_tool_calls([
            _make_tool_call("tc1", "my_tool", "continue"),
        ]),
        _make_tool_result(
            "tc1",
            "partial result",
            custom_content=CustomContent(state=state_data),
        ),
    ]

    tool = _build_tool(messages)
    history = await tool._extract_tool_history("my_tool")

    assert len(history) == 2
    assistant_msg = history[1]
    cc = assistant_msg["custom_content"]
    assert cc["state"] == {"cursor": 42, "mode": "streaming"}


@pytest.mark.asyncio
async def test_extract_resolves_request_attachments():
    """Tool call args with attachment_urls → UserMessageParam has resolved attachments."""
    mock_service = MagicMock()
    mock_service.resolve_attachment_urls = AsyncMock(
        return_value=[
            {"type": "application/pdf", "title": "doc.pdf", "url": "files/xyz/doc.pdf"},
        ]
    )

    messages: list[Message] = [
        Message(role=Role.USER, content=StrictStr("Hello")),
        _make_assistant_with_tool_calls([
            _make_tool_call(
                "tc1", "my_tool", "summarize this", attachment_urls=["files/xyz/doc.pdf"]
            ),
        ]),
        _make_tool_result("tc1", "Summary of the doc"),
    ]

    tool = _build_tool(messages, dial_completion_service=mock_service)
    history = await tool._extract_tool_history("my_tool")

    assert len(history) == 2
    user_msg = history[0]
    assert user_msg["role"] == "user"
    assert user_msg["content"] == "summarize this"
    cc = user_msg["custom_content"]
    assert len(cc["attachments"]) == 1
    assert cc["attachments"][0]["type"] == "application/pdf"
    assert cc["attachments"][0]["title"] == "doc.pdf"

    mock_service.resolve_attachment_urls.assert_awaited_once_with(["files/xyz/doc.pdf"])


# --- Stage propagation: complete_request_async called with propagate_stages and tool_stage_display_name ---


def _build_tool_for_run_in_stage(
    content_propagation: ContentPropagation | None,
    tool_config_display_stage_name: str | None,
    dial_completion_service: Any,
) -> BaseDeploymentTool:
    """Build BaseDeploymentTool for testing _run_in_stage_async propagation args."""
    tool_config = MagicMock()
    tool_config.display = None
    if tool_config_display_stage_name is not None:
        tool_config.display = MagicMock()
        tool_config.display.stage = MagicMock()
        tool_config.display.stage.name = tool_config_display_stage_name
    tool_config.attachment = MagicMock()
    tool_config.attachment.supported_types = []
    tool_config.attachment.propagate_types_to_choice = []
    tool_config.fallback_configuration = None
    tool_config.deployment = MagicMock()
    tool_config.deployment.parameters = MagicMock()
    tool_config.deployment.parameters.model_dump = lambda: {}
    return BaseDeploymentTool(
        application_id="test-app",
        application_name="Test App",
        tool_config=tool_config,
        content_propagation=content_propagation,
        dial_completion_service=dial_completion_service,
        messages=[],
        perf_timer=MagicMock(),
        stage_wrapper_builder=MagicMock(),
    )


@pytest.mark.asyncio
async def test_run_in_stage_calls_complete_with_propagate_stages_and_display_name():
    """When content_propagation.propagate_stages is True and display.stage.name is set, complete_request_async is called with propagate_stages=True and tool_stage_display_name."""
    mock_service = MagicMock()
    mock_service.complete_request_async = AsyncMock(
        return_value=CompletionResult(content="ok", content_type="text/plain")
    )
    tool = _build_tool_for_run_in_stage(
        content_propagation=ContentPropagation(propagate_stages=True),
        tool_config_display_stage_name="Call my-app:",
        dial_completion_service=mock_service,
    )
    stage_wrapper = MagicMock()

    await tool._run_in_stage_async(stage_wrapper=stage_wrapper, query="hello")

    mock_service.complete_request_async.assert_awaited_once()
    call_kwargs = mock_service.complete_request_async.call_args[1]
    assert call_kwargs["propagate_stages"] is True
    assert call_kwargs["tool_stage_display_name"] == "Call my-app:"


@pytest.mark.asyncio
async def test_run_in_stage_propagate_stages_false_when_content_propagation_none():
    """When content_propagation is None, complete_request_async is called with propagate_stages=False."""
    mock_service = MagicMock()
    mock_service.complete_request_async = AsyncMock(
        return_value=CompletionResult(content="ok", content_type="text/plain")
    )
    tool = _build_tool_for_run_in_stage(
        content_propagation=None,
        tool_config_display_stage_name="Call my-app:",
        dial_completion_service=mock_service,
    )

    await tool._run_in_stage_async(stage_wrapper=MagicMock(), query="hello")

    call_kwargs = mock_service.complete_request_async.call_args[1]
    assert call_kwargs["propagate_stages"] is False


@pytest.mark.asyncio
async def test_run_in_stage_propagate_stages_false_when_propagate_stages_disabled():
    """When content_propagation.propagate_stages is False, complete_request_async is called with propagate_stages=False."""
    mock_service = MagicMock()
    mock_service.complete_request_async = AsyncMock(
        return_value=CompletionResult(content="ok", content_type="text/plain")
    )
    tool = _build_tool_for_run_in_stage(
        content_propagation=ContentPropagation(propagate_stages=False),
        tool_config_display_stage_name="Call my-app:",
        dial_completion_service=mock_service,
    )

    await tool._run_in_stage_async(stage_wrapper=MagicMock(), query="hello")

    call_kwargs = mock_service.complete_request_async.call_args[1]
    assert call_kwargs["propagate_stages"] is False


@pytest.mark.asyncio
async def test_run_in_stage_tool_stage_display_name_none_when_no_display_stage():
    """When display or display.stage is missing, complete_request_async is called with tool_stage_display_name=None."""
    mock_service = MagicMock()
    mock_service.complete_request_async = AsyncMock(
        return_value=CompletionResult(content="ok", content_type="text/plain")
    )
    tool = _build_tool_for_run_in_stage(
        content_propagation=ContentPropagation(propagate_stages=True),
        tool_config_display_stage_name=None,
        dial_completion_service=mock_service,
    )

    await tool._run_in_stage_async(stage_wrapper=MagicMock(), query="hello")

    call_kwargs = mock_service.complete_request_async.call_args[1]
    assert call_kwargs["propagate_stages"] is True
    assert call_kwargs["tool_stage_display_name"] is None
