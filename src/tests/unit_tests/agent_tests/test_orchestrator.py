import pytest
from types import SimpleNamespace
from unittest.mock import Mock, AsyncMock

from quickapp.agent.orchestrator import Orchestrator
from quickapp.agent.models import TOOL_EXECUTION_HISTORY
from quickapp.common import DeploymentUsage


@pytest.mark.asyncio
async def test_invoke_no_tool_calls_processes_usage_and_sets_state():
    # Mocks and simple objects
    presentation_settings = SimpleNamespace(show_usage_statistics=True)
    messages_context = Mock()
    messages_context.append_message = Mock()
    messages_context.messages = []

    choice = Mock()
    choice.add_attachment = Mock()
    choice.set_state = Mock()

    # assistant call result without tool calls, with usage
    assistant_result = SimpleNamespace(
        content="response",
        attachments=[],
        tool_calls=[],
        usage=SimpleNamespace(prompt_tokens=5, completion_tokens=7),
    )

    assistant_invoker = Mock()
    assistant_invoker.invoke = AsyncMock(return_value="stream")
    assistant_invoker_provider = Mock(get=Mock(return_value=assistant_invoker))

    chunk_processor = Mock()
    chunk_processor.process_chunks = AsyncMock(return_value=assistant_result)
    chunk_processor_provider = Mock(get=Mock(return_value=chunk_processor))

    state_holder = Mock()
    initial_state = {"some": "state"}
    state_holder.get_state = Mock(return_value=initial_state)
    state_holder.add_state = Mock()

    usage_statistics_service = Mock()
    usage_statistics_service.process_usage_statistics = AsyncMock()

    tool_executor = Mock()

    app_config = SimpleNamespace(
        orchestrator=SimpleNamespace(max_iterations=5, deployment=SimpleNamespace(name="test-model"))
    )

    orchestrator = Orchestrator(
        presentation_settings=presentation_settings,
        messages_context=messages_context,
        choice=choice,
        state_holder=state_holder,
        usage_statistics_service=usage_statistics_service,
        tool_executor=tool_executor,
        assistant_invoker_provider=assistant_invoker_provider,
        chunk_processor_provider=chunk_processor_provider,
        app_config=app_config,
    )

    await orchestrator.invoke()

    # choice.set_state should be called with the state from state_holder
    choice.set_state.assert_called_once_with(initial_state)

    # usage_statistics_service.process_usage_statistics should be awaited with a list
    usage_statistics_service.process_usage_statistics.assert_awaited_once()
    called_arg = usage_statistics_service.process_usage_statistics.call_args[0][0]
    assert isinstance(called_arg, list)
    assert len(called_arg) == 1
    assert isinstance(called_arg[0], DeploymentUsage)
    assert called_arg[0].model_name == "test-model"


@pytest.mark.asyncio
async def test_invoke_with_tool_calls_executes_tools_and_updates_state_and_messages():
    # Mocks and simple objects
    presentation_settings = SimpleNamespace(show_usage_statistics=True)
    messages_context = Mock()
    messages_context.append_message = Mock()
    messages_context.messages = []

    choice = Mock()
    choice.add_attachment = Mock()
    choice.set_state = Mock()

    # First assistant result contains tool_calls, second has none (to end recursion)
    assistant_result_with_tools = SimpleNamespace(
        content="call tool",
        attachments=[],
        # Provide full tool call shape expected by pydantic Message validation
        tool_calls=[
            {
                "id": "tc-1",
                "type": "function",
                "function": {"name": "tool_a", "arguments": "{}"},
            }
        ],
        usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
    )
    assistant_result_no_tools = SimpleNamespace(
        content="final",
        attachments=[],
        tool_calls=[],
        usage=SimpleNamespace(prompt_tokens=2, completion_tokens=2),
    )

    assistant_invoker = Mock()
    assistant_invoker.invoke = AsyncMock(return_value="stream")
    assistant_invoker_provider = Mock(get=Mock(return_value=assistant_invoker))

    chunk_processor = Mock()
    # Return with tools first, then without tools to stop recursion
    chunk_processor.process_chunks = AsyncMock(side_effect=[assistant_result_with_tools, assistant_result_no_tools])
    chunk_processor_provider = Mock(get=Mock(return_value=chunk_processor))

    state_holder = Mock()
    # initial execution history empty
    state_holder.get_state = Mock(return_value={TOOL_EXECUTION_HISTORY: []})
    state_holder.add_state = Mock()

    usage_statistics_service = Mock()
    usage_statistics_service.process_usage_statistics = AsyncMock()

    # Prepare tool executor result
    # Use a dict shaped like a Message so pydantic can validate it
    tool_message = {"role": "assistant", "content": "tool output"}
    tool_result = Mock()
    tool_result.to_tool_message = Mock(return_value=tool_message)

    # propagate_to_choice contains attachments with model_dump()
    attach = Mock()
    attach.model_dump = Mock(return_value={"id": "att1", "content": "data"})
    tool_result.propagate_to_choice = [attach]

    # tool_result.usage is a list compatible with DeploymentUsage instances
    tool_result.usage = [DeploymentUsage(model_name="test-model", prompt_tokens=3, completion_tokens=4)]

    tool_executor = Mock()
    tool_executor.execute = AsyncMock(return_value=[tool_result])

    app_config = SimpleNamespace(
        orchestrator=SimpleNamespace(max_iterations=10, deployment=SimpleNamespace(name="test-model"))
    )

    orchestrator = Orchestrator(
        presentation_settings=presentation_settings,
        messages_context=messages_context,
        choice=choice,
        state_holder=state_holder,
        usage_statistics_service=usage_statistics_service,
        tool_executor=tool_executor,
        assistant_invoker_provider=assistant_invoker_provider,
        chunk_processor_provider=chunk_processor_provider,
        app_config=app_config,
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
    choice.add_attachment.assert_called_once_with(**attach.model_dump())

    # state_holder.add_state should be called to store TOOL_EXECUTION_HISTORY
    state_holder.add_state.assert_called()
    key, value = state_holder.add_state.call_args[0]
    assert key == TOOL_EXECUTION_HISTORY
    assert isinstance(value, list)
    assert len(value) >= 1


@pytest.mark.asyncio
async def test_invoke_tool_calls_returns_no_results_raises_runtime_error():
    presentation_settings = SimpleNamespace(show_usage_statistics=True)

    messages_context = Mock()
    messages_context.append_message = Mock()
    messages_context.messages = []

    choice = Mock()
    choice.add_attachment = Mock()
    choice.set_state = Mock()

    # Assistant result contains a properly shaped tool_call entry
    assistant_result_with_tools = SimpleNamespace(
        content="call tool",
        attachments=[],
        tool_calls=[
            {"id": "tc-1", "type": "function", "function": {"name": "tool_a", "arguments": "{}"}}
        ],
        usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
    )

    assistant_invoker = Mock()
    assistant_invoker.invoke = AsyncMock(return_value="stream")
    assistant_invoker_provider = Mock(get=Mock(return_value=assistant_invoker))

    chunk_processor = Mock()
    chunk_processor.process_chunks = AsyncMock(return_value=assistant_result_with_tools)
    chunk_processor_provider = Mock(get=Mock(return_value=chunk_processor))

    state_holder = Mock()
    state_holder.get_state = Mock(return_value={})
    state_holder.add_state = Mock()

    usage_statistics_service = Mock()
    usage_statistics_service.process_usage_statistics = AsyncMock()

    # Tool executor returns no results (falsy) to trigger the error path
    tool_executor = Mock()
    tool_executor.execute = AsyncMock(return_value=[])

    app_config = SimpleNamespace(
        orchestrator=SimpleNamespace(max_iterations=5, deployment=SimpleNamespace(name="test-model"))
    )

    orchestrator = Orchestrator(
        presentation_settings=presentation_settings,
        messages_context=messages_context,
        choice=choice,
        state_holder=state_holder,
        usage_statistics_service=usage_statistics_service,
        tool_executor=tool_executor,
        assistant_invoker_provider=assistant_invoker_provider,
        chunk_processor_provider=chunk_processor_provider,
        app_config=app_config,
    )

    with pytest.raises(RuntimeError) as excinfo:
        await orchestrator.invoke()

    assert "doesn't return any result" in str(excinfo.value)
    tool_executor.execute.assert_awaited_once()