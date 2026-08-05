"""Unit tests for Orchestrator external tool routing (partition logic)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from aidial_sdk.chat_completion.request import Message, Role

from quickapp.common.chat_completion_stream.tool_call import AccumulatedToolCall
from quickapp.common.request_async_close_registry import RequestAsyncCloseRegistry
from quickapp.common.stage_close_registry import DeferredStageCloseRegistry
from quickapp.core.agent import Orchestrator
from quickapp.core.agent.models import TOOL_EXECUTION_HISTORY
from tests.unit_tests.stream_test_doubles import SpyChoice


def _make_tool_call(id: str, name: str, arguments: str = "{}") -> AccumulatedToolCall:
    tc = AccumulatedToolCall()
    tc._id = id
    tc._name = name
    tc._arguments = arguments
    return tc


def _make_orchestrator(
    messages_list: list[Message],
    tool_names: frozenset[str],
    stream_handler_side_effect,
    tool_executor: Mock | None = None,
) -> tuple[Orchestrator, SpyChoice]:
    messages_context = Mock()
    messages_context.append_message = Mock(side_effect=lambda msg: messages_list.append(msg))
    messages_context.messages = messages_list

    choice = SpyChoice()

    assistant_invoker = Mock()
    assistant_invoker.invoke = AsyncMock(return_value="stream")
    assistant_invoker_provider = Mock(get=Mock(return_value=assistant_invoker))

    stream_handler = Mock()
    stream_handler.process_stream = AsyncMock(side_effect=stream_handler_side_effect)

    orch = Orchestrator(
        presentation_settings=SimpleNamespace(show_usage_statistics=False),
        messages_context=messages_context,
        choice=choice,
        state_holder=Mock(get_state=Mock(return_value={}), add_state=Mock()),
        usage_statistics_service=Mock(process_usage_statistics=AsyncMock()),
        tool_executor=tool_executor or Mock(execute=AsyncMock(return_value=[])),
        assistant_invoker_provider=assistant_invoker_provider,
        stream_handler=stream_handler,
        app_config=SimpleNamespace(
            orchestrator=SimpleNamespace(
                max_iterations=10,
                deployment=SimpleNamespace(deployment_id="m"),
                propagate_stages=True,
            )
        ),
        perf_timer=Mock(),
        deferred_stage_close_registry=DeferredStageCloseRegistry(),
        chat_completion_recovery=Mock(apply_message_recovery=Mock()),
        tool_execution_history_policies=[],
        tool_names=tool_names,
        request_async_close_registry=RequestAsyncCloseRegistry(),
    )
    return orch, choice


def _stream_result(tool_calls=None, content="response"):
    return SimpleNamespace(
        content=content,
        attachments=[],
        tool_calls=tool_calls or [],
        usage=None,
        state=None,
        adopted_tool_stages={},
        close_remaining_adopted_tool_stages=Mock(),
    )


@pytest.mark.asyncio
async def test_all_external_tool_calls_are_surfaced_and_loop_stops():
    messages_list: list[Message] = [Message(role=Role.USER, content="hi")]
    tc = _make_tool_call("id-1", "ext_tool")
    result = _stream_result(tool_calls=[tc])

    orch, choice = _make_orchestrator(
        messages_list,
        tool_names=frozenset({"ext_tool"}),
        stream_handler_side_effect=[result],
    )

    await orch.invoke()

    assert choice._last_finish_reason is not None
    assert choice._last_finish_reason.value == "tool_calls"


@pytest.mark.asyncio
async def test_all_external_tool_calls_surfaced_with_correct_id_name_args():
    messages_list: list[Message] = [Message(role=Role.USER, content="hi")]
    tc1 = _make_tool_call("id-1", "ext_a", '{"x": 1}')
    tc2 = _make_tool_call("id-2", "ext_b", '{"y": 2}')
    result = _stream_result(tool_calls=[tc1, tc2])

    tool_call_records: list[tuple] = []

    class RecordingChoice(SpyChoice):
        def create_function_tool_call(self, id, name, arguments=None):
            tool_call_records.append((id, name, arguments))
            return super().create_function_tool_call(id, name, arguments)

    messages_context = Mock()
    messages_context.append_message = Mock(side_effect=lambda m: messages_list.append(m))
    messages_context.messages = messages_list
    choice = RecordingChoice()

    assistant_invoker = Mock()
    assistant_invoker.invoke = AsyncMock(return_value="stream")
    assistant_invoker_provider = Mock(get=Mock(return_value=assistant_invoker))

    stream_handler = Mock()
    stream_handler.process_stream = AsyncMock(return_value=result)

    orch = Orchestrator(
        presentation_settings=SimpleNamespace(show_usage_statistics=False),
        messages_context=messages_context,
        choice=choice,
        state_holder=Mock(get_state=Mock(return_value={}), add_state=Mock()),
        usage_statistics_service=Mock(process_usage_statistics=AsyncMock()),
        tool_executor=Mock(execute=AsyncMock(return_value=[])),
        assistant_invoker_provider=assistant_invoker_provider,
        stream_handler=stream_handler,
        app_config=SimpleNamespace(
            orchestrator=SimpleNamespace(
                max_iterations=10,
                deployment=SimpleNamespace(deployment_id="m"),
                propagate_stages=True,
            )
        ),
        perf_timer=Mock(),
        deferred_stage_close_registry=DeferredStageCloseRegistry(),
        chat_completion_recovery=Mock(apply_message_recovery=Mock()),
        tool_execution_history_policies=[],
        tool_names=frozenset({"ext_a", "ext_b"}),
        request_async_close_registry=RequestAsyncCloseRegistry(),
    )

    await orch.invoke()

    assert len(tool_call_records) == 2
    assert tool_call_records[0] == ("id-1", "ext_a", '{"x": 1}')
    assert tool_call_records[1] == ("id-2", "ext_b", '{"y": 2}')


@pytest.mark.asyncio
async def test_mixed_batch_executes_internal_and_surfaces_external():
    messages_list: list[Message] = [Message(role=Role.USER, content="hi")]
    tc_internal = _make_tool_call("id-i", "server_tool")
    tc_external = _make_tool_call("id-e", "ext_tool")
    result = _stream_result(tool_calls=[tc_internal, tc_external])

    tool_call_records: list[tuple] = []

    class RecordingChoice(SpyChoice):
        def create_function_tool_call(self, id, name, arguments=None):
            tool_call_records.append((id, name, arguments))
            return super().create_function_tool_call(id, name, arguments)

    messages_context = Mock()
    messages_context.append_message = Mock(side_effect=lambda m: messages_list.append(m))
    messages_context.messages = messages_list
    choice = RecordingChoice()

    assistant_invoker = Mock()
    assistant_invoker.invoke = AsyncMock(return_value="stream")
    assistant_invoker_provider = Mock(get=Mock(return_value=assistant_invoker))

    stream_handler = Mock()
    stream_handler.process_stream = AsyncMock(return_value=result)

    tool_msg = Message(role=Role.TOOL, content="server result", tool_call_id="id-i")
    tool_result = Mock()
    tool_result.to_tool_message = Mock(return_value=tool_msg)
    tool_result.propagate_to_choice = []
    tool_result.usage = None

    tool_executor = Mock(
        execute=AsyncMock(return_value=[tool_result]),
    )

    orch = Orchestrator(
        presentation_settings=SimpleNamespace(show_usage_statistics=False),
        messages_context=messages_context,
        choice=choice,
        state_holder=Mock(get_state=Mock(return_value={}), add_state=Mock()),
        usage_statistics_service=Mock(process_usage_statistics=AsyncMock()),
        tool_executor=tool_executor,
        assistant_invoker_provider=assistant_invoker_provider,
        stream_handler=stream_handler,
        app_config=SimpleNamespace(
            orchestrator=SimpleNamespace(
                max_iterations=10,
                deployment=SimpleNamespace(deployment_id="m"),
                propagate_stages=True,
            )
        ),
        perf_timer=Mock(),
        deferred_stage_close_registry=DeferredStageCloseRegistry(),
        chat_completion_recovery=Mock(apply_message_recovery=Mock()),
        tool_execution_history_policies=[],
        tool_names=frozenset({"ext_tool"}),
        request_async_close_registry=RequestAsyncCloseRegistry(),
    )

    await orch.invoke()

    # Internal tool was executed
    tool_executor.execute.assert_awaited_once()
    called_internal = tool_executor.execute.call_args[0][0]
    assert len(called_internal) == 1
    assert called_internal[0].name == "server_tool"

    # TOOL message for server result was appended
    messages_context.append_message.assert_any_call(tool_msg)

    # External tool was surfaced
    assert len(tool_call_records) == 1
    assert tool_call_records[0] == ("id-e", "ext_tool", "{}")

    # Loop stopped (no second LLM call)
    assert stream_handler.process_stream.await_count == 1


@pytest.mark.asyncio
async def test_all_internal_tools_loop_continues():
    messages_list: list[Message] = [Message(role=Role.USER, content="hi")]
    tc = _make_tool_call("id-1", "server_tool")
    result_with_tool = _stream_result(tool_calls=[tc], content="calling tool")
    result_final = _stream_result(tool_calls=[], content="done")

    tool_msg = Message(role=Role.TOOL, content="ok", tool_call_id="id-1")
    tool_result = Mock()
    tool_result.to_tool_message = Mock(return_value=tool_msg)
    tool_result.propagate_to_choice = []
    tool_result.usage = None
    tool_executor = Mock(
        execute=AsyncMock(return_value=[tool_result]),
    )

    messages_context = Mock()
    messages_context.append_message = Mock(side_effect=lambda m: messages_list.append(m))
    messages_context.messages = messages_list
    choice = SpyChoice()

    assistant_invoker = Mock()
    assistant_invoker.invoke = AsyncMock(return_value="stream")
    assistant_invoker_provider = Mock(get=Mock(return_value=assistant_invoker))

    stream_handler = Mock()
    stream_handler.process_stream = AsyncMock(side_effect=[result_with_tool, result_final])

    orch = Orchestrator(
        presentation_settings=SimpleNamespace(show_usage_statistics=False),
        messages_context=messages_context,
        choice=choice,
        state_holder=Mock(get_state=Mock(return_value={}), add_state=Mock()),
        usage_statistics_service=Mock(process_usage_statistics=AsyncMock()),
        tool_executor=tool_executor,
        assistant_invoker_provider=assistant_invoker_provider,
        stream_handler=stream_handler,
        app_config=SimpleNamespace(
            orchestrator=SimpleNamespace(
                max_iterations=10,
                deployment=SimpleNamespace(deployment_id="m"),
                propagate_stages=True,
            )
        ),
        perf_timer=Mock(),
        deferred_stage_close_registry=DeferredStageCloseRegistry(),
        chat_completion_recovery=Mock(apply_message_recovery=Mock()),
        tool_execution_history_policies=[],
        tool_names=frozenset({"some_ext_tool"}),  # server_tool is NOT external
        request_async_close_registry=RequestAsyncCloseRegistry(),
    )

    await orch.invoke()

    # Two LLM calls: first with tool, second final
    assert stream_handler.process_stream.await_count == 2
    # Tool was executed
    tool_executor.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_no_external_tools_configured_existing_behavior_unchanged():
    """With empty external_tool_names, all tool calls are treated as internal."""
    messages_list: list[Message] = [Message(role=Role.USER, content="hi")]
    tc = _make_tool_call("id-1", "any_tool")
    result_with_tool = _stream_result(tool_calls=[tc])
    result_final = _stream_result(tool_calls=[])

    tool_msg = Message(role=Role.TOOL, content="ok", tool_call_id="id-1")
    tool_result = Mock()
    tool_result.to_tool_message = Mock(return_value=tool_msg)
    tool_result.propagate_to_choice = []
    tool_result.usage = None
    tool_executor = Mock(
        execute=AsyncMock(return_value=[tool_result]),
    )

    messages_context = Mock()
    messages_context.append_message = Mock(side_effect=lambda m: messages_list.append(m))
    messages_context.messages = messages_list
    choice = SpyChoice()

    assistant_invoker = Mock()
    assistant_invoker.invoke = AsyncMock(return_value="stream")
    assistant_invoker_provider = Mock(get=Mock(return_value=assistant_invoker))

    stream_handler = Mock()
    stream_handler.process_stream = AsyncMock(side_effect=[result_with_tool, result_final])

    orch = Orchestrator(
        presentation_settings=SimpleNamespace(show_usage_statistics=False),
        messages_context=messages_context,
        choice=choice,
        state_holder=Mock(get_state=Mock(return_value={}), add_state=Mock()),
        usage_statistics_service=Mock(process_usage_statistics=AsyncMock()),
        tool_executor=tool_executor,
        assistant_invoker_provider=assistant_invoker_provider,
        stream_handler=stream_handler,
        app_config=SimpleNamespace(
            orchestrator=SimpleNamespace(
                max_iterations=10,
                deployment=SimpleNamespace(deployment_id="m"),
                propagate_stages=True,
            )
        ),
        perf_timer=Mock(),
        deferred_stage_close_registry=DeferredStageCloseRegistry(),
        chat_completion_recovery=Mock(apply_message_recovery=Mock()),
        tool_execution_history_policies=[],
        tool_names=frozenset(),
        request_async_close_registry=RequestAsyncCloseRegistry(),
    )

    await orch.invoke()

    assert stream_handler.process_stream.await_count == 2
    tool_executor.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_mixed_batch_persists_history_without_external_tool_calls():
    """In a mixed batch, persisted history strips external tool_calls from the ASSISTANT."""
    messages_list: list[Message] = [Message(role=Role.USER, content="hi")]
    tc_internal = _make_tool_call("id-i", "server_tool")
    tc_external = _make_tool_call("id-e", "ext_tool")
    result = _stream_result(tool_calls=[tc_internal, tc_external])

    tool_msg = Message(role=Role.TOOL, content="server result", tool_call_id="id-i")
    tool_result = Mock()
    tool_result.to_tool_message = Mock(return_value=tool_msg)
    tool_result.propagate_to_choice = []
    tool_result.usage = None
    tool_executor = Mock(
        execute=AsyncMock(return_value=[tool_result]),
    )

    messages_context = Mock()
    messages_context.append_message = Mock(side_effect=lambda m: messages_list.append(m))
    messages_context.messages = messages_list

    state_holder = Mock(get_state=Mock(return_value={}), add_state=Mock())
    choice = SpyChoice()

    assistant_invoker = Mock()
    assistant_invoker.invoke = AsyncMock(return_value="stream")
    assistant_invoker_provider = Mock(get=Mock(return_value=assistant_invoker))

    stream_handler = Mock()
    stream_handler.process_stream = AsyncMock(return_value=result)

    orch = Orchestrator(
        presentation_settings=SimpleNamespace(show_usage_statistics=False),
        messages_context=messages_context,
        choice=choice,
        state_holder=state_holder,
        usage_statistics_service=Mock(process_usage_statistics=AsyncMock()),
        tool_executor=tool_executor,
        assistant_invoker_provider=assistant_invoker_provider,
        stream_handler=stream_handler,
        app_config=SimpleNamespace(
            orchestrator=SimpleNamespace(
                max_iterations=10,
                deployment=SimpleNamespace(deployment_id="m"),
                propagate_stages=True,
            )
        ),
        perf_timer=Mock(),
        deferred_stage_close_registry=DeferredStageCloseRegistry(),
        chat_completion_recovery=Mock(apply_message_recovery=Mock()),
        tool_execution_history_policies=[],
        tool_names=frozenset({"ext_tool"}),
        request_async_close_registry=RequestAsyncCloseRegistry(),
    )

    await orch.invoke()

    # Find the add_state call for TOOL_EXECUTION_HISTORY
    history_call = next(
        call
        for call in state_holder.add_state.call_args_list
        if call[0][0] == TOOL_EXECUTION_HISTORY
    )
    history = history_call[0][1]

    # History should have ASSISTANT + TOOL
    assert len(history) == 2
    assert history[0]["role"] == "assistant"
    assert history[1]["role"] == "tool"

    # The ASSISTANT in history should only have the internal tool call
    assistant_tool_calls = history[0]["tool_calls"]
    assert len(assistant_tool_calls) == 1
    assert assistant_tool_calls[0]["function"]["name"] == "server_tool"
