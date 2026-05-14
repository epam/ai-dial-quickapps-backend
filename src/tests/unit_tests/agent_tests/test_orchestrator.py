from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock

import openai
import pytest
from aidial_sdk.chat_completion.request import (
    Attachment,
    CustomContent,
    FunctionCall,
    Message,
    Role,
    ToolCall,
)

from quickapp.agent.models import STATE_KEY_ORCHESTRATOR, TOOL_EXECUTION_HISTORY
from quickapp.agent.orchestrator import Orchestrator
from quickapp.common import DeploymentUsage
from quickapp.common.chat_completion_stream.tool_call import AccumulatedToolCall
from quickapp.common.stage_close_registry import DeferredStageCloseRegistry
from tests.unit_tests.stream_test_doubles import SpyChoice

GET_CONTENT_TOOL_NAME = "internal_attachments_get_content"


def _make_accumulated_tool_call(id: str, name: str, arguments: str = "{}") -> AccumulatedToolCall:
    tc = AccumulatedToolCall()
    tc._id = id
    tc._name = name
    tc._arguments = arguments
    return tc


@pytest.mark.asyncio
async def test_invoke_no_tool_calls_processes_usage_and_sets_state():
    # Mocks and simple objects
    presentation_settings = SimpleNamespace(show_usage_statistics=True)

    messages_list: list[Message] = []
    messages_context = Mock()
    messages_context.append_message = Mock(side_effect=lambda msg: messages_list.append(msg))
    messages_context.messages = messages_list

    choice = SpyChoice()

    # assistant call result without tool calls, with usage
    assistant_result = SimpleNamespace(
        content="response",
        attachments=[],
        tool_calls=[],
        usage=SimpleNamespace(prompt_tokens=5, completion_tokens=7),
        state=None,
    )

    assistant_invoker = Mock()
    assistant_invoker.invoke = AsyncMock(return_value="stream")
    assistant_invoker_provider = Mock(get=Mock(return_value=assistant_invoker))

    stream_handler = Mock()
    stream_handler.process_stream = AsyncMock(return_value=assistant_result)

    state_holder = Mock()
    initial_state = {"some": "state"}
    state_holder.get_state = Mock(return_value=initial_state)
    state_holder.add_state = Mock()

    usage_statistics_service = Mock()
    usage_statistics_service.process_usage_statistics = AsyncMock()

    tool_executor = Mock()

    app_config = SimpleNamespace(
        orchestrator=SimpleNamespace(
            max_iterations=5,
            deployment=SimpleNamespace(deployment_id="test-model"),
            propagate_stages=True,
        )
    )

    orchestrator = Orchestrator(
        presentation_settings=presentation_settings,
        messages_context=messages_context,
        choice=choice,
        state_holder=state_holder,
        usage_statistics_service=usage_statistics_service,
        tool_executor=tool_executor,
        assistant_invoker_provider=assistant_invoker_provider,
        stream_handler=stream_handler,
        app_config=app_config,
        perf_timer=Mock(),
        deferred_stage_close_registry=DeferredStageCloseRegistry(),
        chat_completion_recovery_policies=[],
        tool_execution_history_policies=[],
    )

    await orchestrator.invoke()

    # No tool calls and no stream state: nothing to add (no tool_execution_history, no orchestrator state)
    state_holder.add_state.assert_not_called()

    # choice.set_state should be called with the state from state_holder
    assert choice.set_state_calls == [initial_state]

    # usage_statistics_service.process_usage_statistics should be awaited with a list
    usage_statistics_service.process_usage_statistics.assert_awaited_once()
    called_arg = usage_statistics_service.process_usage_statistics.call_args[0][0]
    assert isinstance(called_arg, list)
    assert len(called_arg) == 1
    assert isinstance(called_arg[0], DeploymentUsage)
    assert called_arg[0].model_name == "test-model"


@pytest.mark.asyncio
async def test_stream_phase_api_error_retries_after_recovery():
    presentation_settings = SimpleNamespace(show_usage_statistics=False)

    messages_list: list[Message] = []
    messages_context = Mock()
    messages_context.append_message = Mock(side_effect=lambda msg: messages_list.append(msg))
    messages_context.messages = messages_list

    choice = SpyChoice()

    assistant_result = SimpleNamespace(
        content="response",
        attachments=[],
        tool_calls=[],
        usage=None,
        state=None,
    )

    api_err = openai.APIError(message="Unsupported media type", request=MagicMock(), body=None)

    assistant_invoker = Mock()
    assistant_invoker.invoke = AsyncMock(return_value="stream")
    assistant_invoker_provider = Mock(get=Mock(return_value=assistant_invoker))

    stream_handler = Mock()
    stream_handler.process_stream = AsyncMock(side_effect=[api_err, assistant_result])

    recovery_policy = Mock()
    recovery_policy.try_recover.return_value = True

    deferred_registry = Mock(spec=DeferredStageCloseRegistry)

    orchestrator = Orchestrator(
        presentation_settings=presentation_settings,
        messages_context=messages_context,
        choice=choice,
        state_holder=Mock(get_state=Mock(return_value={}), add_state=Mock()),
        usage_statistics_service=Mock(process_usage_statistics=AsyncMock()),
        tool_executor=Mock(),
        assistant_invoker_provider=assistant_invoker_provider,
        stream_handler=stream_handler,
        app_config=SimpleNamespace(
            orchestrator=SimpleNamespace(
                max_iterations=5,
                deployment=SimpleNamespace(deployment_id="test-model"),
                propagate_stages=True,
            )
        ),
        perf_timer=Mock(),
        deferred_stage_close_registry=deferred_registry,
        chat_completion_recovery_policies=[recovery_policy],
        tool_execution_history_policies=[],
    )

    await orchestrator.invoke()

    assert assistant_invoker.invoke.await_count == 2
    assert stream_handler.process_stream.await_count == 2
    recovery_policy.try_recover.assert_called_once()
    assert recovery_policy.try_recover.call_args[0][0] is messages_list
    assert recovery_policy.try_recover.call_args[0][1] is api_err
    deferred_registry.sync_deferred_stage_ui_with_tool_messages.assert_called_once_with(
        messages_list
    )


@pytest.mark.asyncio
async def test_stream_phase_api_error_raises_when_recovery_no_op():
    presentation_settings = SimpleNamespace(show_usage_statistics=False)

    messages_list: list[Message] = []
    messages_context = Mock()
    messages_context.append_message = Mock(side_effect=lambda msg: messages_list.append(msg))
    messages_context.messages = messages_list

    choice = SpyChoice()

    api_err = openai.APIError(message="upstream", request=MagicMock(), body=None)

    assistant_invoker = Mock()
    assistant_invoker.invoke = AsyncMock(return_value="stream")
    assistant_invoker_provider = Mock(get=Mock(return_value=assistant_invoker))

    stream_handler = Mock()
    stream_handler.process_stream = AsyncMock(side_effect=api_err)

    recovery_policy = Mock()
    recovery_policy.try_recover.return_value = False

    orchestrator = Orchestrator(
        presentation_settings=presentation_settings,
        messages_context=messages_context,
        choice=choice,
        state_holder=Mock(get_state=Mock(return_value={}), add_state=Mock()),
        usage_statistics_service=Mock(process_usage_statistics=AsyncMock()),
        tool_executor=Mock(),
        assistant_invoker_provider=assistant_invoker_provider,
        stream_handler=stream_handler,
        app_config=SimpleNamespace(
            orchestrator=SimpleNamespace(
                max_iterations=5,
                deployment=SimpleNamespace(deployment_id="test-model"),
                propagate_stages=True,
            )
        ),
        perf_timer=Mock(),
        deferred_stage_close_registry=DeferredStageCloseRegistry(),
        chat_completion_recovery_policies=[recovery_policy],
        tool_execution_history_policies=[],
    )

    with pytest.raises(openai.APIError):
        await orchestrator.invoke()

    assert assistant_invoker.invoke.await_count == 1
    assert stream_handler.process_stream.await_count == 1


@pytest.mark.asyncio
async def test_invoke_with_tool_calls_executes_tools_and_updates_state_and_messages():
    # Mocks and simple objects
    presentation_settings = SimpleNamespace(show_usage_statistics=True)

    messages_list: list[Message] = [Message(role=Role.USER, content="hello")]
    messages_context = Mock()
    messages_context.append_message = Mock(side_effect=lambda msg: messages_list.append(msg))
    messages_context.messages = messages_list

    choice = SpyChoice()

    # First assistant result contains tool_calls, second has none (to end loop)
    assistant_result_with_tools = SimpleNamespace(
        content="call tool",
        attachments=[],
        tool_calls=[_make_accumulated_tool_call(id="tc-1", name="tool_a")],
        usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
        state=None,
    )
    assistant_result_no_tools = SimpleNamespace(
        content="final",
        attachments=[],
        tool_calls=[],
        usage=SimpleNamespace(prompt_tokens=2, completion_tokens=2),
        state=None,
    )

    assistant_invoker = Mock()
    assistant_invoker.invoke = AsyncMock(return_value="stream")
    assistant_invoker_provider = Mock(get=Mock(return_value=assistant_invoker))

    stream_handler = Mock()
    # Return with tools first, then without tools to stop loop
    stream_handler.process_stream = AsyncMock(
        side_effect=[assistant_result_with_tools, assistant_result_no_tools]
    )

    state_holder = Mock()
    state_holder.get_state = Mock(return_value={})
    state_holder.add_state = Mock()

    usage_statistics_service = Mock()
    usage_statistics_service.process_usage_statistics = AsyncMock()

    # Prepare tool executor result — tool message must be a real Message for the helper
    tool_message = Message(role=Role.TOOL, content="tool output", tool_call_id="tc-1")
    tool_result = Mock()
    tool_result.to_tool_message = Mock(return_value=tool_message)

    # propagate_to_choice contains attachments with model_dump()
    attach = Mock()
    attach.model_dump = Mock(return_value={"id": "att1", "content": "data"})
    tool_result.propagate_to_choice = [attach]

    # tool_result.usage is a list compatible with DeploymentUsage instances
    tool_result.usage = [
        DeploymentUsage(model_name="test-model", prompt_tokens=3, completion_tokens=4)
    ]

    tool_executor = Mock()
    tool_executor.execute = AsyncMock(return_value=[tool_result])

    app_config = SimpleNamespace(
        orchestrator=SimpleNamespace(
            max_iterations=10,
            deployment=SimpleNamespace(deployment_id="test-model"),
            propagate_stages=True,
        )
    )

    orchestrator = Orchestrator(
        presentation_settings=presentation_settings,
        messages_context=messages_context,
        choice=choice,
        state_holder=state_holder,
        usage_statistics_service=usage_statistics_service,
        tool_executor=tool_executor,
        assistant_invoker_provider=assistant_invoker_provider,
        stream_handler=stream_handler,
        app_config=app_config,
        perf_timer=Mock(),
        deferred_stage_close_registry=DeferredStageCloseRegistry(),
        chat_completion_recovery_policies=[],
        tool_execution_history_policies=[],
    )

    await orchestrator.invoke()

    # tool_executor.execute must have been called with the tool_calls from the first assistant result
    tool_executor.execute.assert_awaited_once()
    called_with_tool_calls = tool_executor.execute.call_args[0][0]
    assert called_with_tool_calls == assistant_result_with_tools.tool_calls

    # append_message should be called for the tool result message
    messages_context.append_message.assert_any_call(tool_message)

    # attachments should be propagated to choice via add_attachment
    attach.model_dump.assert_called()
    assert len(choice.add_attachment_kwargs) == 1
    assert choice.add_attachment_kwargs[0] == attach.model_dump()

    # state_holder.add_state called once in finally with tool_execution_history (no stream state in mocks)
    state_holder.add_state.assert_called_once()
    key, value = state_holder.add_state.call_args[0]
    assert key == TOOL_EXECUTION_HISTORY
    assert isinstance(value, list)
    # New format stores messages directly: ASSISTANT + TOOL = 2 messages
    assert len(value) == 2
    assert value[0]["role"] == "assistant"
    assert value[1]["role"] == "tool"


@pytest.mark.asyncio
async def test_invoke_with_stream_state_puts_only_response_state_under_orchestrator():
    """state.orchestrator contains only response state (e.g. claude_message_content), not stages."""
    messages_list: list[Message] = []
    messages_context = Mock()
    messages_context.append_message = Mock(side_effect=lambda msg: messages_list.append(msg))
    messages_context.messages = messages_list

    choice = SpyChoice()

    stream_state = {"claude_message_content": "thinking output"}
    assistant_result = SimpleNamespace(
        content="response",
        attachments=[],
        tool_calls=[],
        usage=SimpleNamespace(prompt_tokens=1, completion_tokens=2),
        state=stream_state,
        stages=[{"name": "Thinking", "content": "..."}],  # stages must not appear in state
    )

    assistant_invoker = Mock()
    assistant_invoker.invoke = AsyncMock(return_value="stream")
    assistant_invoker_provider = Mock(get=Mock(return_value=assistant_invoker))

    stream_handler = Mock()
    stream_handler.process_stream = AsyncMock(return_value=assistant_result)

    state_holder = Mock()
    state_holder.get_state = Mock(return_value={})
    state_holder.add_state = Mock()

    orchestrator = Orchestrator(
        presentation_settings=SimpleNamespace(show_usage_statistics=False),
        messages_context=messages_context,
        choice=choice,
        state_holder=state_holder,
        usage_statistics_service=Mock(process_usage_statistics=AsyncMock()),
        tool_executor=Mock(),
        assistant_invoker_provider=assistant_invoker_provider,
        stream_handler=stream_handler,
        app_config=SimpleNamespace(
            orchestrator=SimpleNamespace(
                max_iterations=5,
                deployment=SimpleNamespace(deployment_id="m"),
                propagate_stages=True,
            )
        ),
        perf_timer=Mock(),
        deferred_stage_close_registry=DeferredStageCloseRegistry(),
        chat_completion_recovery_policies=[],
        tool_execution_history_policies=[],
    )

    await orchestrator.invoke()

    # Appended message has state.orchestrator = response state only (no "stages")
    assert len(messages_list) == 1
    msg = messages_list[0]
    assert msg.custom_content is not None
    state = msg.custom_content.state
    assert state is not None
    assert STATE_KEY_ORCHESTRATOR in state
    orch = state[STATE_KEY_ORCHESTRATOR]
    assert orch == {"claude_message_content": "thinking output"}
    assert "stages" not in orch

    # state_holder received orchestrator state (response state only)
    state_holder.add_state.assert_called()
    orch_calls = [
        c[0] for c in state_holder.add_state.call_args_list if c[0][0] == STATE_KEY_ORCHESTRATOR
    ]
    assert len(orch_calls) == 1
    assert orch_calls[0][1] == stream_state


@pytest.mark.asyncio
async def test_invoke_tool_calls_returns_no_results_raises_runtime_error():
    presentation_settings = SimpleNamespace(show_usage_statistics=True)

    messages_list: list[Message] = []
    messages_context = Mock()
    messages_context.append_message = Mock(side_effect=lambda msg: messages_list.append(msg))
    messages_context.messages = messages_list

    choice = SpyChoice()

    # Assistant result contains a properly shaped tool_call entry
    assistant_result_with_tools = SimpleNamespace(
        content="call tool",
        attachments=[],
        tool_calls=[_make_accumulated_tool_call(id="tc-1", name="tool_a")],
        usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
        state=None,
    )

    assistant_invoker = Mock()
    assistant_invoker.invoke = AsyncMock(return_value="stream")
    assistant_invoker_provider = Mock(get=Mock(return_value=assistant_invoker))

    stream_handler = Mock()
    stream_handler.process_stream = AsyncMock(return_value=assistant_result_with_tools)

    state_holder = Mock()
    state_holder.get_state = Mock(return_value={})
    state_holder.add_state = Mock()

    usage_statistics_service = Mock()
    usage_statistics_service.process_usage_statistics = AsyncMock()

    # Tool executor returns no results (falsy) to trigger the error path
    tool_executor = Mock()
    tool_executor.execute = AsyncMock(return_value=[])

    app_config = SimpleNamespace(
        orchestrator=SimpleNamespace(
            max_iterations=5,
            deployment=SimpleNamespace(deployment_id="test-model"),
            propagate_stages=True,
        )
    )

    orchestrator = Orchestrator(
        presentation_settings=presentation_settings,
        messages_context=messages_context,
        choice=choice,
        state_holder=state_holder,
        usage_statistics_service=usage_statistics_service,
        tool_executor=tool_executor,
        assistant_invoker_provider=assistant_invoker_provider,
        stream_handler=stream_handler,
        app_config=app_config,
        perf_timer=Mock(),
        deferred_stage_close_registry=DeferredStageCloseRegistry(),
        chat_completion_recovery_policies=[],
        tool_execution_history_policies=[],
    )

    with pytest.raises(RuntimeError) as excinfo:
        await orchestrator.invoke()

    assert "doesn't return any result" in str(excinfo.value)
    tool_executor.execute.assert_awaited_once()


def _make_tool_call(call_id: str, name: str = "tool_a") -> ToolCall:
    return ToolCall(
        id=call_id,
        type="function",
        function=FunctionCall(name=name, arguments="{}"),
    )


def _make_orchestrator(messages_list: list[Message]) -> Orchestrator:
    messages_context = Mock()
    messages_context.append_message = Mock(side_effect=lambda msg: messages_list.append(msg))
    messages_context.messages = messages_list

    return Orchestrator(
        presentation_settings=SimpleNamespace(show_usage_statistics=False),
        messages_context=messages_context,
        choice=Mock(add_attachment=Mock(), set_state=Mock()),
        state_holder=Mock(get_state=Mock(return_value={}), add_state=Mock()),
        usage_statistics_service=Mock(process_usage_statistics=AsyncMock()),
        tool_executor=Mock(),
        assistant_invoker_provider=Mock(),
        stream_handler=Mock(),
        app_config=SimpleNamespace(
            orchestrator=SimpleNamespace(
                max_iterations=10,
                deployment=SimpleNamespace(deployment_id="m"),
                propagate_stages=True,
            )
        ),
        perf_timer=Mock(),
        deferred_stage_close_registry=DeferredStageCloseRegistry(),
        chat_completion_recovery_policies=[],
        tool_execution_history_policies=[],
    )


class TestBuildToolExecutionHistory:
    def test_empty_messages_returns_empty(self):
        orchestrator = _make_orchestrator([])
        result = orchestrator._build_tool_execution_history()
        assert result == []

    def test_only_user_and_final_assistant_returns_empty(self):
        messages = [
            Message(role=Role.USER, content="hello"),
            Message(role=Role.ASSISTANT, content="hi there"),
        ]
        orchestrator = _make_orchestrator(messages)
        result = orchestrator._build_tool_execution_history()
        assert result == []

    def test_single_tool_call_iteration(self):
        messages = [
            Message(role=Role.USER, content="hello"),
            Message(
                role=Role.ASSISTANT,
                content="",
                tool_calls=[_make_tool_call("tc-1")],
            ),
            Message(role=Role.TOOL, content="result-1", tool_call_id="tc-1"),
            Message(role=Role.ASSISTANT, content="done"),
        ]
        orchestrator = _make_orchestrator(messages)
        result = orchestrator._build_tool_execution_history()
        assert len(result) == 2
        assert result[0]["role"] == "assistant"
        assert result[1]["role"] == "tool"

    def test_multiple_iterations(self):
        messages = [
            Message(role=Role.USER, content="hello"),
            # Iteration 1
            Message(
                role=Role.ASSISTANT,
                content="",
                tool_calls=[_make_tool_call("tc-1")],
            ),
            Message(role=Role.TOOL, content="result-1", tool_call_id="tc-1"),
            # Iteration 2
            Message(
                role=Role.ASSISTANT,
                content="",
                tool_calls=[_make_tool_call("tc-2", name="tool_b")],
            ),
            Message(role=Role.TOOL, content="result-2", tool_call_id="tc-2"),
            # Final
            Message(role=Role.ASSISTANT, content="all done"),
        ]
        orchestrator = _make_orchestrator(messages)
        result = orchestrator._build_tool_execution_history()

        assert len(result) == 4
        assert result[0]["role"] == "assistant"
        assert result[1]["role"] == "tool"
        assert result[2]["role"] == "assistant"
        assert result[3]["role"] == "tool"

    def test_parallel_tool_calls_preserved(self):
        messages = [
            Message(role=Role.USER, content="hello"),
            Message(
                role=Role.ASSISTANT,
                content="",
                tool_calls=[_make_tool_call("tc-1"), _make_tool_call("tc-2", name="tool_b")],
            ),
            Message(role=Role.TOOL, content="result-1", tool_call_id="tc-1"),
            Message(role=Role.TOOL, content="result-2", tool_call_id="tc-2"),
            Message(role=Role.ASSISTANT, content="done"),
        ]
        orchestrator = _make_orchestrator(messages)
        result = orchestrator._build_tool_execution_history()

        assert len(result) == 3
        # Single ASSISTANT with both tool_calls
        assert result[0]["role"] == "assistant"
        assert len(result[0]["tool_calls"]) == 2
        assert result[1]["role"] == "tool"
        assert result[2]["role"] == "tool"

    def test_stops_at_last_user_message(self):
        messages = [
            # Earlier turn (should be excluded)
            Message(role=Role.USER, content="first"),
            Message(
                role=Role.ASSISTANT,
                content="",
                tool_calls=[_make_tool_call("tc-old")],
            ),
            Message(role=Role.TOOL, content="old-result", tool_call_id="tc-old"),
            Message(role=Role.ASSISTANT, content="first answer"),
            # Current turn
            Message(role=Role.USER, content="second"),
            Message(
                role=Role.ASSISTANT,
                content="",
                tool_calls=[_make_tool_call("tc-new")],
            ),
            Message(role=Role.TOOL, content="new-result", tool_call_id="tc-new"),
            Message(role=Role.ASSISTANT, content="second answer"),
        ]
        orchestrator = _make_orchestrator(messages)
        result = orchestrator._build_tool_execution_history()

        # Only current turn's tool call pair
        assert len(result) == 2
        assert result[0]["role"] == "assistant"
        assert result[0]["tool_calls"][0]["id"] == "tc-new"
        assert result[1]["role"] == "tool"
        assert result[1]["content"] == "new-result"

    def test_final_assistant_without_tool_calls_excluded(self):
        messages = [
            Message(role=Role.USER, content="hello"),
            Message(
                role=Role.ASSISTANT,
                content="",
                tool_calls=[_make_tool_call("tc-1")],
            ),
            Message(role=Role.TOOL, content="result", tool_call_id="tc-1"),
            Message(role=Role.ASSISTANT, content="final answer"),  # no tool_calls
        ]
        orchestrator = _make_orchestrator(messages)
        result = orchestrator._build_tool_execution_history()

        # Final ASSISTANT without tool_calls is excluded
        assert len(result) == 2
        assert all(r["role"] != "assistant" or "tool_calls" in r for r in result)

    def test_history_includes_synthetic_get_content_pair_in_current_turn(self):
        messages = [
            Message(role=Role.USER, content="first"),
            Message(
                role=Role.ASSISTANT,
                content="",
                tool_calls=[_make_tool_call("tc-old", name=GET_CONTENT_TOOL_NAME)],
            ),
            Message(role=Role.TOOL, content='{"ok": true}', tool_call_id="tc-old"),
            Message(role=Role.ASSISTANT, content="answer one"),
            Message(role=Role.USER, content="second"),
            Message(
                role=Role.ASSISTANT,
                content="",
                tool_calls=[_make_tool_call("tc-synth", name=GET_CONTENT_TOOL_NAME)],
            ),
            Message(
                role=Role.TOOL,
                content='{"ok": true, "url": "files/bucket/new.pdf"}',
                tool_call_id="tc-synth",
                custom_content=CustomContent(
                    attachments=[
                        Attachment(
                            title="new.pdf",
                            type="application/pdf",
                            url="files/bucket/new.pdf",
                        )
                    ]
                ),
            ),
            Message(role=Role.ASSISTANT, content="answer two"),
        ]
        orchestrator = _make_orchestrator(messages)
        result = orchestrator._build_tool_execution_history()

        assert len(result) == 2
        assert result[0]["role"] == "assistant"
        assert result[0]["tool_calls"][0]["id"] == "tc-synth"
        assert result[1]["role"] == "tool"
        assert result[1]["tool_call_id"] == "tc-synth"
