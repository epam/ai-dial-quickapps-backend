import copy
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from aidial_sdk.chat_completion import Message, Role
from aidial_sdk.chat_completion.request import Attachment as SdkAttachment
from aidial_sdk.chat_completion.request import CustomContent, FunctionCall, ToolCall
from pydantic import StrictStr

from quickapp.common.messages_mixin import MessagesMixin
from quickapp.common.tool_call_result import ToolCallResult
from quickapp.config.application import StageDisplayLevel
from quickapp.config.dial_deployment import (
    CustomFieldsConfig,
    DialDeploymentConfig,
    DialDeploymentParameters,
)
from quickapp.config.tools.base import (
    ConfigurableSchemaSimpleType,
    JsonTypeEnum,
    OpenAiToolConfig,
    OpenAiToolFunction,
    OpenAiToolFunctionParameters,
)
from quickapp.config.tools.deployment import (
    ContentPropagation,
    ConversationMode,
    DialDeploymentTool,
)
from quickapp.dial_deployment_tooling.base_deployment_tool import BaseDeploymentTool


def _make_messages_mixin(messages: list[Message]) -> MessagesMixin:
    mixin = MessagesMixin()
    mixin.messages = messages
    return mixin


def _make_tool_call(
    tool_call_id: str,
    name: str,
    query: str,
    attachment_urls: list[str] | None = None,
    session_id: str | None = None,
) -> ToolCall:
    args: dict[str, Any] = {"query": query}
    if attachment_urls is not None:
        args["attachment_urls"] = attachment_urls
    if session_id is not None:
        args["session_id"] = session_id
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
    attachment_resolver: Any = None,
) -> BaseDeploymentTool:
    """Build a BaseDeploymentTool with minimal mocks for testing _extract_tool_history."""
    if dial_completion_service is None:
        dial_completion_service = MagicMock()
    if attachment_resolver is None:
        attachment_resolver = MagicMock()
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
        attachment_resolver=attachment_resolver,
        messages_mixin=_make_messages_mixin(messages),
        perf_timer=MagicMock(),
        stage_wrapper_builder=MagicMock(),
        stage_display_level=StageDisplayLevel.INFO,
    )


@pytest.mark.asyncio
async def test_extract_single_tool_history():
    """Single tool with two prior interactions extracts correctly."""
    messages: list[Message] = [
        Message(role=Role.USER, content=StrictStr("Help me")),
        _make_assistant_with_tool_calls(
            [
                _make_tool_call("tc1", "my_tool", "First question"),
            ]
        ),
        _make_tool_result("tc1", "First answer"),
        _make_assistant_with_tool_calls(
            [
                _make_tool_call("tc2", "my_tool", "Second question"),
            ]
        ),
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
        _make_assistant_with_tool_calls(
            [
                _make_tool_call("tc_a1", "tool_a", "question for A"),
                _make_tool_call("tc_b1", "tool_b", "question for B"),
            ]
        ),
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
        _make_assistant_with_tool_calls(
            [
                _make_tool_call("tc1", "my_tool", "old question"),
            ]
        ),
        _make_tool_result("tc1", "old answer"),
        # Current call — no TOOL result appended yet
        _make_assistant_with_tool_calls(
            [
                _make_tool_call("tc2", "my_tool", "current question"),
            ]
        ),
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
        _make_assistant_with_tool_calls(
            [
                _make_tool_call("tc_late", "my_tool", "late question"),
            ]
        )
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
        _make_assistant_with_tool_calls(
            [
                _make_tool_call("tc1", "other_tool", "question"),
            ]
        ),
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
        _make_assistant_with_tool_calls(
            [
                _make_tool_call("tc1", "my_tool", "describe image"),
            ]
        ),
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
        _make_assistant_with_tool_calls(
            [
                _make_tool_call("tc1", "my_tool", "continue"),
            ]
        ),
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
    mock_resolver = MagicMock()
    mock_resolver.resolve_attachment_urls = AsyncMock(
        return_value=[
            {"type": "application/pdf", "title": "doc.pdf", "url": "files/xyz/doc.pdf"},
        ]
    )

    messages: list[Message] = [
        Message(role=Role.USER, content=StrictStr("Hello")),
        _make_assistant_with_tool_calls(
            [
                _make_tool_call(
                    "tc1", "my_tool", "summarize this", attachment_urls=["files/xyz/doc.pdf"]
                ),
            ]
        ),
        _make_tool_result("tc1", "Summary of the doc"),
    ]

    tool = _build_tool(messages, attachment_resolver=mock_resolver)
    history = await tool._extract_tool_history("my_tool")

    assert len(history) == 2
    user_msg = history[0]
    assert user_msg["role"] == "user"
    assert user_msg["content"] == "summarize this"
    cc = user_msg["custom_content"]
    assert len(cc["attachments"]) == 1
    assert cc["attachments"][0]["type"] == "application/pdf"
    assert cc["attachments"][0]["title"] == "doc.pdf"

    mock_resolver.resolve_attachment_urls.assert_awaited_once()
    awaited_args, awaited_kwargs = mock_resolver.resolve_attachment_urls.await_args
    assert awaited_args[0] == ["files/xyz/doc.pdf"]
    assert "supports_url_attachments" in awaited_kwargs


def _make_tool_config(
    parameters: DialDeploymentParameters | None = None,
    configuration_param_names: set[str] | None = None,
) -> DialDeploymentTool:
    """Build a real DialDeploymentTool for _pre_process_params tests."""
    deployment = DialDeploymentConfig(
        deployment_id="test-deployment",
        parameters=parameters or DialDeploymentParameters(),
    )
    if configuration_param_names:
        deployment._configuration_param_names = configuration_param_names
    return DialDeploymentTool(
        deployment=deployment,
        open_ai_tool=OpenAiToolConfig(
            function=OpenAiToolFunction(
                name="test_tool",
                description="A test tool",
                parameters=OpenAiToolFunctionParameters(
                    type=JsonTypeEnum.object,
                    properties={
                        "query": ConfigurableSchemaSimpleType(
                            type=JsonTypeEnum.string, description="The query"
                        ),
                    },
                    required=["query"],
                ),
            )
        ),
    )


def _build_tool_with_config(
    tool_config: DialDeploymentTool,
    messages: list[Message] | None = None,
) -> BaseDeploymentTool:
    """Build a BaseDeploymentTool with a real tool_config for _pre_process_params tests."""
    return BaseDeploymentTool(
        application_id="test-app",
        application_name="Test App",
        tool_config=tool_config,
        content_propagation=None,
        dial_completion_service=MagicMock(),
        attachment_resolver=MagicMock(),
        messages_mixin=_make_messages_mixin(messages or []),
        perf_timer=MagicMock(),
        stage_wrapper_builder=MagicMock(),
        stage_display_level=StageDisplayLevel.INFO,
    )


@pytest.mark.asyncio
async def test_pre_process_params_wraps_config_params():
    """Configuration params are wrapped into custom_fields.configuration."""
    tool_config = _make_tool_config(configuration_param_names={"size", "quality"})
    tool = _build_tool_with_config(tool_config)

    result = await tool._pre_process_params(query="draw a cat", size="1024x1024", quality="high")

    assert result["query"] == "draw a cat"
    assert result["custom_fields"]["configuration"]["size"] == "1024x1024"
    assert result["custom_fields"]["configuration"]["quality"] == "high"
    assert "size" not in {k for k in result if k != "custom_fields"}
    assert "quality" not in {k for k in result if k != "custom_fields"}


@pytest.mark.asyncio
async def test_pre_process_params_merges_defaults_with_llm_config():
    """LLM config params override defaults; unset defaults are preserved."""
    params = DialDeploymentParameters(
        custom_fields=CustomFieldsConfig(configuration={"size": "512x512", "style": "natural"})
    )
    tool_config = _make_tool_config(
        parameters=params, configuration_param_names={"size", "quality"}
    )
    tool = _build_tool_with_config(tool_config)

    result = await tool._pre_process_params(query="draw", size="1024x1024")

    config = result["custom_fields"]["configuration"]
    assert config["size"] == "1024x1024"  # LLM overrides default
    assert config["style"] == "natural"  # default preserved


@pytest.mark.asyncio
async def test_pre_process_params_no_config_names_stays_flat():
    """With no configuration_param_names, all kwargs remain flat (backward compat)."""
    tool_config = _make_tool_config()
    tool = _build_tool_with_config(tool_config)

    result = await tool._pre_process_params(query="draw", custom_key="value")

    assert result["query"] == "draw"
    assert result["custom_key"] == "value"
    assert "custom_fields" not in result


@pytest.mark.asyncio
async def test_pre_process_params_standard_params_stay_flat():
    """Standard API params like temperature stay flat even when config params exist."""
    tool_config = _make_tool_config(configuration_param_names={"size"})
    tool = _build_tool_with_config(tool_config)

    result = await tool._pre_process_params(query="draw", size="1024x1024", temperature=0.7)

    assert result["temperature"] == 0.7
    assert "temperature" not in result.get("custom_fields", {}).get("configuration", {})
    assert result["custom_fields"]["configuration"]["size"] == "1024x1024"


# ---------------------------------------------------------------------------
# _extract_tool_history: empty content with state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extract_preserves_state_with_empty_content():
    """TOOL message with state but empty content still produces an AssistantMessageParam with state."""
    state_data = {"tool_execution_history": [{"role": "assistant", "content": "step 1"}]}
    messages: list[Message] = [
        Message(role=Role.USER, content=StrictStr("Hello")),
        _make_assistant_with_tool_calls([_make_tool_call("tc1", "my_tool", "go")]),
        _make_tool_result("tc1", "", custom_content=CustomContent(state=state_data)),
    ]

    tool = _build_tool(messages)
    history = await tool._extract_tool_history("my_tool")

    assert len(history) == 2
    assistant_msg = history[1]
    assert assistant_msg["role"] == "assistant"
    assert assistant_msg["content"] == ""
    assert assistant_msg["custom_content"]["state"] == state_data


# ---------------------------------------------------------------------------
# conversation_mode: _run_in_stage_async history triggering
# ---------------------------------------------------------------------------


def _build_tool_with_propagation(
    messages: list[Message],
    content_propagation: ContentPropagation | None,
    dial_completion_service: Any = None,
) -> BaseDeploymentTool:
    """Build a BaseDeploymentTool with a real tool_config and configurable content_propagation."""
    if dial_completion_service is None:
        dial_completion_service = AsyncMock()
    return BaseDeploymentTool(
        application_id="test-app",
        application_name="Test App",
        tool_config=_make_tool_config(),
        content_propagation=content_propagation,
        dial_completion_service=dial_completion_service,
        attachment_resolver=MagicMock(),
        messages_mixin=_make_messages_mixin(messages),
        perf_timer=MagicMock(),
        stage_wrapper_builder=MagicMock(),
        stage_display_level=StageDisplayLevel.INFO,
    )


def _make_mock_completion_service() -> Any:
    svc = AsyncMock()
    svc.complete_request_async.return_value = ToolCallResult(
        content="ok", content_type="text/plain"
    )
    return svc


@pytest.mark.asyncio
async def test_conversation_mode_stateful_triggers_extract():
    """conversation_mode=stateful causes history to be built and passed to the service."""
    svc = _make_mock_completion_service()
    tool = _build_tool_with_propagation(
        messages=[],
        content_propagation=ContentPropagation(conversation_mode=ConversationMode.STATEFUL),
        dial_completion_service=svc,
    )

    await tool._run_in_stage_async(stage_wrapper=None, query="hello")

    _, kwargs = svc.complete_request_async.call_args
    assert kwargs["history"] is not None


@pytest.mark.asyncio
async def test_conversation_mode_stateless_skips_extract():
    """conversation_mode=stateless with propagate_history=False passes history=None."""
    svc = _make_mock_completion_service()
    tool = _build_tool_with_propagation(
        messages=[],
        content_propagation=ContentPropagation(
            conversation_mode=ConversationMode.STATELESS,
            propagate_history=False,
        ),
        dial_completion_service=svc,
    )

    await tool._run_in_stage_async(stage_wrapper=None, query="hello")

    _, kwargs = svc.complete_request_async.call_args
    assert kwargs["history"] is None


@pytest.mark.asyncio
async def test_propagate_history_and_stateful_are_independent():
    """propagate_history=True and conversation_mode=stateful each independently trigger extraction."""
    for propagation in [
        ContentPropagation(propagate_history=True, conversation_mode=ConversationMode.STATELESS),
        ContentPropagation(propagate_history=False, conversation_mode=ConversationMode.STATEFUL),
    ]:
        svc = _make_mock_completion_service()
        tool = _build_tool_with_propagation(
            messages=[],
            content_propagation=propagation,
            dial_completion_service=svc,
        )

        await tool._run_in_stage_async(stage_wrapper=None, query="hello")

        _, kwargs = svc.complete_request_async.call_args
        assert kwargs["history"] is not None, f"Expected history for {propagation}"


# ---------------------------------------------------------------------------
# _extract_tool_history: session_id filtering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extract_session_id_filters_to_matching_thread():
    """Anchor call (tc.id == session_id) and follow-ups (args session_id == session_id) are included; other threads excluded."""
    messages: list[Message] = [
        Message(role=Role.USER, content=StrictStr("Start")),
        _make_assistant_with_tool_calls(
            [
                _make_tool_call("tc1", "my_tool", "thread-A step 1"),  # anchor for session tc1
                _make_tool_call("tc2", "my_tool", "thread-B step 1"),  # anchor for session tc2
            ]
        ),
        _make_tool_result("tc1", "A answer 1"),
        _make_tool_result("tc2", "B answer 1"),
        _make_assistant_with_tool_calls(
            [
                _make_tool_call(
                    "tc3", "my_tool", "thread-A step 2", session_id="tc1"
                ),  # follow-up to A
            ]
        ),
        _make_tool_result("tc3", "A answer 2"),
    ]

    tool = _build_tool(messages)
    history = await tool._extract_tool_history("my_tool", session_id="tc1")

    assert len(history) == 4
    assert history[0]["content"] == "thread-A step 1"
    assert history[1]["content"] == "A answer 1"
    assert history[2]["content"] == "thread-A step 2"
    assert history[3]["content"] == "A answer 2"


@pytest.mark.asyncio
async def test_extract_anchor_matches_by_tool_call_id():
    """First call matched by tc.id == session_id (the anchor), even without session_id in its args."""
    messages: list[Message] = [
        Message(role=Role.USER, content=StrictStr("Start")),
        _make_assistant_with_tool_calls([_make_tool_call("call-abc", "my_tool", "first question")]),
        _make_tool_result("call-abc", "first answer"),
    ]

    tool = _build_tool(messages)
    history = await tool._extract_tool_history("my_tool", session_id="call-abc")

    assert len(history) == 2
    assert history[0]["content"] == "first question"
    assert history[1]["content"] == "first answer"


@pytest.mark.asyncio
async def test_extract_session_id_excludes_other_threads():
    """Calls with a different session_id are not included."""
    messages: list[Message] = [
        Message(role=Role.USER, content=StrictStr("Start")),
        _make_assistant_with_tool_calls(
            [
                _make_tool_call("tc1", "my_tool", "thread-A step", session_id="session-A"),
            ]
        ),
        _make_tool_result("tc1", "A answer"),
    ]

    tool = _build_tool(messages)
    history = await tool._extract_tool_history("my_tool", session_id="session-B")

    assert history == []


@pytest.mark.asyncio
async def test_extract_session_id_none_falls_back_to_tool_name_only():
    """When session_id is None, falls back to tool_name-only filtering (includes all sessions)."""
    messages: list[Message] = [
        Message(role=Role.USER, content=StrictStr("Start")),
        _make_assistant_with_tool_calls(
            [
                _make_tool_call("tc1", "my_tool", "thread-A", session_id="session-A"),
                _make_tool_call("tc2", "my_tool", "thread-B", session_id="session-B"),
            ]
        ),
        _make_tool_result("tc1", "A answer"),
        _make_tool_result("tc2", "B answer"),
    ]

    tool = _build_tool(messages)
    history = await tool._extract_tool_history("my_tool", session_id=None)

    assert len(history) == 4
    assert history[0]["content"] == "thread-A"
    assert history[1]["content"] == "A answer"
    assert history[2]["content"] == "thread-B"
    assert history[3]["content"] == "B answer"


# ---------------------------------------------------------------------------
# _run_in_stage_async: session_id is consumed, not forwarded to subagent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_in_stage_pops_session_id_before_forwarding():
    """session_id is consumed by _run_in_stage_async and not forwarded to the completion service."""
    svc = _make_mock_completion_service()
    tool = _build_tool_with_propagation(
        messages=[],
        content_propagation=ContentPropagation(conversation_mode=ConversationMode.STATEFUL),
        dial_completion_service=svc,
    )

    await tool._run_in_stage_async(stage_wrapper=None, query="hello", session_id="my-thread")

    forwarded_kwargs, _ = svc.complete_request_async.call_args
    payload = forwarded_kwargs[0]
    assert "session_id" not in payload
    assert payload["query"] == "hello"


@pytest.mark.asyncio
async def test_run_in_stage_injects_session_id_into_first_result():
    """First stateful call (no session_id) appends session_id from tool_call_id to result content."""
    svc = _make_mock_completion_service()
    tool = _build_tool_with_propagation(
        messages=[],
        content_propagation=ContentPropagation(conversation_mode=ConversationMode.STATEFUL),
        dial_completion_service=svc,
    )

    result = await tool._run_in_stage_async(
        stage_wrapper=None, tool_call_id="call-xyz", query="hello"
    )

    assert "[session_id: call-xyz]" in result.content


@pytest.mark.asyncio
async def test_run_in_stage_no_injection_on_follow_up():
    """Follow-up call (session_id already provided) does not modify result content."""
    svc = _make_mock_completion_service()
    tool = _build_tool_with_propagation(
        messages=[],
        content_propagation=ContentPropagation(conversation_mode=ConversationMode.STATEFUL),
        dial_completion_service=svc,
    )

    result = await tool._run_in_stage_async(
        stage_wrapper=None, tool_call_id="call-xyz2", query="hello", session_id="call-xyz"
    )

    assert result.content == "ok"


@pytest.mark.asyncio
async def test_run_in_stage_no_injection_for_stateless():
    """Stateless tool calls never inject session_id, even when tool_call_id is present."""
    svc = _make_mock_completion_service()
    tool = _build_tool_with_propagation(
        messages=[],
        content_propagation=ContentPropagation(conversation_mode=ConversationMode.STATELESS),
        dial_completion_service=svc,
    )

    result = await tool._run_in_stage_async(
        stage_wrapper=None, tool_call_id="call-xyz", query="hello"
    )

    assert result.content == "ok"


# ---------------------------------------------------------------------------
# enrich_openai_tool_schema
# ---------------------------------------------------------------------------


def _build_tool_with_content_propagation(
    content_propagation: ContentPropagation | None,
) -> BaseDeploymentTool:
    return BaseDeploymentTool(
        application_id="test-app",
        application_name="Test App",
        tool_config=_make_tool_config(),
        content_propagation=content_propagation,
        dial_completion_service=MagicMock(),
        attachment_resolver=MagicMock(),
        messages_mixin=_make_messages_mixin([]),
        perf_timer=MagicMock(),
        stage_wrapper_builder=MagicMock(),
        stage_display_level=StageDisplayLevel.INFO,
    )


def test_enrich_stateful_injects_session_id():
    """For conversation_mode=stateful, enrich_openai_tool_schema injects session_id into the schema."""
    tool = _build_tool_with_content_propagation(
        ContentPropagation(conversation_mode=ConversationMode.STATEFUL)
    )
    tool_config = _make_tool_config()
    open_ai_tool = copy.deepcopy(tool_config.open_ai_tool)
    enriched = tool.enrich_openai_tool_schema(open_ai_tool)

    assert "session_id" in enriched.function.parameters.properties


def test_enrich_stateless_is_noop():
    """For conversation_mode=stateless (default), enrich_openai_tool_schema returns the tool unchanged."""
    tool = _build_tool_with_content_propagation(
        ContentPropagation(conversation_mode=ConversationMode.STATELESS)
    )
    tool_config = _make_tool_config()
    open_ai_tool = copy.deepcopy(tool_config.open_ai_tool)
    original_description = open_ai_tool.function.description
    original_props = set(open_ai_tool.function.parameters.properties.keys())

    enriched = tool.enrich_openai_tool_schema(open_ai_tool)

    assert enriched.function.description == original_description
    assert set(enriched.function.parameters.properties.keys()) == original_props


def test_enrich_no_propagation_is_noop():
    """With no content_propagation, enrich_openai_tool_schema is a no-op."""
    tool = _build_tool_with_content_propagation(None)
    tool_config = _make_tool_config()
    open_ai_tool = copy.deepcopy(tool_config.open_ai_tool)
    original_props = set(open_ai_tool.function.parameters.properties.keys())

    enriched = tool.enrich_openai_tool_schema(open_ai_tool)

    assert set(enriched.function.parameters.properties.keys()) == original_props
