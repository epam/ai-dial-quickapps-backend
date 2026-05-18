from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock

import openai
import pytest

from quickapp.agent.assistant_invoker import AssistantInvoker
from quickapp.common.stage_close_registry import DeferredStageCloseRegistry


# Minimal test helpers
def _presentation_settings(show_usage: bool):
    return SimpleNamespace(show_usage_statistics=show_usage)


def _agent_settings(chat_message_log_length=None):
    return SimpleNamespace(chat_message_log_length=chat_message_log_length)


class FakeMessage:
    def __init__(self, content: str):
        self.content = content

    def model_dump(self, exclude_none=True, mode=None):
        return {"role": "user", "content": self.content}

    def dict(self):
        return {"role": "user", "content": self.content}


class DummyParams:
    def model_dump(self, exclude_none=True):
        # base config returned before payload update
        return {"base_param": "value"}


class DummyDeployment:
    def __init__(self):
        self.parameters = DummyParams()
        self.deployment_id = "test-model"


class DummyOrchestrator:
    def __init__(self):
        self.deployment = DummyDeployment()


class DummyConfig:
    def __init__(self):
        self.orchestrator = DummyOrchestrator()


mock_filter = Mock()
mock_filter.transform.side_effect = lambda messages: messages


@pytest.mark.asyncio
async def test_invoke_without_show_usage(monkeypatch):
    # Prepare mocked azure client
    create_mock = AsyncMock(return_value="stream-result")
    azure_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create_mock))
    )

    tools = [{"name": "t1"}]
    invoker = AssistantInvoker(
        tools=tools,
        config=DummyConfig(),
        messages=[FakeMessage("hello")],
        choice=SimpleNamespace(),  # not used in code under test
        azure_client=azure_client,
        response_format=None,
        pre_invocation_transformers=[mock_filter],
        presentation_settings=_presentation_settings(False),
        agent_settings=_agent_settings(),
        forwarded_headers=None,
        chat_completion_recovery_policies=[],
        deferred_stage_close_registry=DeferredStageCloseRegistry(),
    )

    result = await invoker.invoke()
    assert result == "stream-result"
    # capture kwargs the create call was invoked with
    assert create_mock.await_count == 1
    called_kwargs = create_mock.await_args.args
    # create is called with kwargs only (no positional args)
    assert called_kwargs == ()
    called_kwargs = create_mock.await_args.kwargs
    # base param merged with payload keys
    assert called_kwargs["base_param"] == "value"
    assert called_kwargs["model"] == "test-model"
    assert called_kwargs["stream"] is True
    assert called_kwargs["messages"] == [{"role": "user", "content": "hello"}]
    assert called_kwargs["tools"] == tools
    # stream_options must NOT be present when show_usage_statistics is False
    assert "stream_options" not in called_kwargs


@pytest.mark.asyncio
async def test_invoke_with_show_usage_true(monkeypatch):
    create_mock = AsyncMock(return_value="stream-result")
    azure_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create_mock))
    )

    tools = [{"name": "t2"}]
    invoker = AssistantInvoker(
        tools=tools,
        config=DummyConfig(),
        messages=[FakeMessage("hello2")],
        choice=SimpleNamespace(),
        azure_client=azure_client,
        pre_invocation_transformers=[mock_filter],
        response_format=None,
        presentation_settings=_presentation_settings(True),
        agent_settings=_agent_settings(),
        forwarded_headers=None,
        chat_completion_recovery_policies=[],
        deferred_stage_close_registry=DeferredStageCloseRegistry(),
    )

    result = await invoker.invoke()
    assert result == "stream-result"
    assert create_mock.await_count == 1
    called_kwargs = create_mock.await_args.kwargs
    # stream_options should be present and include_usage True
    assert "stream_options" in called_kwargs
    assert called_kwargs["stream_options"] == {"include_usage": True}
    # other keys still correct
    assert called_kwargs["tools"] == tools
    assert called_kwargs["messages"] == [{"role": "user", "content": "hello2"}]
    assert called_kwargs["stream"] is True


@pytest.mark.asyncio
async def test_invoke_propagates_exceptions():
    """Exceptions from the azure client are re-raised without transformation.
    Error-to-message translation is handled upstream by _exception_message_resolver."""
    create_mock = AsyncMock(side_effect=RuntimeError("upstream failure"))
    azure_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create_mock))
    )

    invoker = AssistantInvoker(
        tools=[{"name": "t"}],
        config=DummyConfig(),
        messages=[FakeMessage("oops")],
        choice=SimpleNamespace(),
        azure_client=azure_client,
        pre_invocation_transformers=[mock_filter],
        response_format=None,
        presentation_settings=_presentation_settings(False),
        agent_settings=_agent_settings(),
        forwarded_headers=None,
        chat_completion_recovery_policies=[],
        deferred_stage_close_registry=DeferredStageCloseRegistry(),
    )

    with pytest.raises(RuntimeError, match="upstream failure"):
        await invoker.invoke()

    assert create_mock.await_count == 1


@pytest.mark.asyncio
async def test_invoke_bad_request_retries_after_recovery():
    """BadRequest triggers recovery policies once; successful retry returns stream."""
    policy = Mock()
    policy.try_recover.return_value = True

    stream_ok = "stream-after-recovery"
    create_mock = AsyncMock(
        side_effect=[
            openai.BadRequestError(message="bad", response=MagicMock(status_code=400), body=None),
            stream_ok,
        ]
    )
    azure_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create_mock))
    )

    deferred_registry = Mock(spec=DeferredStageCloseRegistry)
    messages = [FakeMessage("hello")]
    invoker = AssistantInvoker(
        tools=[{"name": "t"}],
        config=DummyConfig(),
        messages=messages,
        choice=SimpleNamespace(),
        azure_client=azure_client,
        response_format=None,
        pre_invocation_transformers=[mock_filter],
        presentation_settings=_presentation_settings(False),
        agent_settings=_agent_settings(),
        forwarded_headers=None,
        chat_completion_recovery_policies=[policy],
        deferred_stage_close_registry=deferred_registry,
    )

    result = await invoker.invoke()
    assert result == stream_ok
    assert create_mock.await_count == 2
    policy.try_recover.assert_called_once()
    deferred_registry.sync_deferred_stage_ui_with_tool_messages.assert_called_once_with(messages)


@pytest.mark.asyncio
async def test_invoke_bad_request_raises_when_recovery_no_op():
    policy = Mock()
    policy.try_recover.return_value = False

    create_mock = AsyncMock(
        side_effect=openai.BadRequestError(
            message="bad", response=MagicMock(status_code=400), body=None
        )
    )
    azure_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create_mock))
    )

    invoker = AssistantInvoker(
        tools=[{"name": "t"}],
        config=DummyConfig(),
        messages=[FakeMessage("hello")],
        choice=SimpleNamespace(),
        azure_client=azure_client,
        response_format=None,
        pre_invocation_transformers=[mock_filter],
        presentation_settings=_presentation_settings(False),
        agent_settings=_agent_settings(),
        forwarded_headers=None,
        chat_completion_recovery_policies=[policy],
        deferred_stage_close_registry=DeferredStageCloseRegistry(),
    )

    with pytest.raises(openai.BadRequestError):
        await invoker.invoke()

    assert create_mock.await_count == 1


def test_promote_orchestrator_state_to_top_level():
    """Before the next orchestrator call, state.orchestrator (response state only) is promoted to top-level."""
    from quickapp.agent.models import STATE_KEY_ORCHESTRATOR as ORCH

    msg = {
        "role": "assistant",
        "content": "ok",
        "custom_content": {
            "state": {
                "tool_execution_history": [{"role": "assistant"}],
                ORCH: {"claude_message_content": "some content"},
            },
        },
    }
    AssistantInvoker._AssistantInvoker__promote_orchestrator_state_to_top_level(msg)
    state = msg["custom_content"]["state"]
    assert ORCH not in state
    assert state["tool_execution_history"] == [{"role": "assistant"}]
    assert state["claude_message_content"] == "some content"


def test_promote_orchestrator_state_no_op_no_custom_content():
    """Message without custom_content is unchanged."""
    promote = AssistantInvoker._AssistantInvoker__promote_orchestrator_state_to_top_level
    msg = {"role": "user", "content": "hi"}
    promote(msg)
    assert "custom_content" not in msg


def test_promote_orchestrator_state_no_op_custom_content_not_dict():
    """custom_content that is not a dict is left unchanged (no crash)."""
    promote = AssistantInvoker._AssistantInvoker__promote_orchestrator_state_to_top_level
    msg = {"role": "assistant", "custom_content": None}
    promote(msg)
    assert msg["custom_content"] is None

    msg2 = {"role": "assistant", "custom_content": "invalid"}
    promote(msg2)
    assert msg2["custom_content"] == "invalid"


def test_promote_orchestrator_state_no_op_no_orchestrator_key():
    """State without 'orchestrator' key is unchanged."""
    from quickapp.agent.models import STATE_KEY_ORCHESTRATOR as ORCH

    promote = AssistantInvoker._AssistantInvoker__promote_orchestrator_state_to_top_level
    msg = {
        "custom_content": {
            "state": {"tool_execution_history": [], "other": "x"},
        },
    }
    promote(msg)
    assert msg["custom_content"]["state"] == {"tool_execution_history": [], "other": "x"}
    assert ORCH not in msg["custom_content"]["state"]


def test_promote_orchestrator_state_orchestrator_non_dict_removes_key_only():
    """If state.orchestrator is not a dict, key is removed but state is not updated (no crash)."""
    from quickapp.agent.models import STATE_KEY_ORCHESTRATOR as ORCH

    promote = AssistantInvoker._AssistantInvoker__promote_orchestrator_state_to_top_level
    msg = {
        "custom_content": {
            "state": {"other": "keep", ORCH: [{"stages": "invalid"}]},
        },
    }
    promote(msg)
    state = msg["custom_content"]["state"]
    assert ORCH not in state
    assert state["other"] == "keep"
    assert "stages" not in state
