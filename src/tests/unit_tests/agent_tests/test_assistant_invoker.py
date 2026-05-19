from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock

import openai
import pytest

from quickapp.agent._chat_completion_config_builder import _ChatCompletionConfigBuilder
from quickapp.agent.assistant_invoker import AssistantInvoker
from quickapp.common.chat_completion_recovery import ChatCompletionRecoveryService
from quickapp.common.messages_mixin import MessagesMixin
from quickapp.common.stage_close_registry import DeferredStageCloseRegistry


def _presentation_settings(show_usage: bool):
    return SimpleNamespace(show_usage_statistics=show_usage)


class FakeMessage:
    def __init__(self, content: str):
        self.content = content

    def model_dump(self, exclude_none=True, mode=None):
        return {"role": "user", "content": self.content}

    def dict(self):
        return {"role": "user", "content": self.content}


class DummyParams:
    def model_dump(self, exclude_none=True):
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


def _make_config_builder(
    *,
    config: DummyConfig | None = None,
    tools: list | None = None,
    show_usage: bool = False,
    forwarded_headers=None,
    response_format=None,
) -> _ChatCompletionConfigBuilder:
    return _ChatCompletionConfigBuilder(
        config=config or DummyConfig(),
        tools=tools or [{"name": "t1"}],
        response_format=response_format,
        pre_invocation_transformers=[mock_filter],
        presentation_settings=_presentation_settings(show_usage),
        forwarded_headers=forwarded_headers,
    )


def _make_recovery_service(
    messages,
    *,
    policies=None,
    deferred_stage_close_registry=None,
) -> ChatCompletionRecoveryService:
    messages_mixin = Mock(spec=MessagesMixin)
    messages_mixin.messages = messages
    return ChatCompletionRecoveryService(
        messages_mixin,
        policies or [],
        deferred_stage_close_registry or DeferredStageCloseRegistry(),
    )


def _make_invoker(
    *,
    messages,
    azure_client,
    tools: list | None = None,
    show_usage: bool = False,
    chat_completion_recovery_policies=None,
    deferred_stage_close_registry=None,
    chat_completion_recovery: ChatCompletionRecoveryService | None = None,
    config_builder: _ChatCompletionConfigBuilder | None = None,
) -> AssistantInvoker:
    return AssistantInvoker(
        messages=messages,
        azure_client=azure_client,
        chat_completion_config_builder=config_builder
        or _make_config_builder(tools=tools, show_usage=show_usage),
        chat_completion_recovery=chat_completion_recovery
        or _make_recovery_service(
            messages,
            policies=chat_completion_recovery_policies,
            deferred_stage_close_registry=deferred_stage_close_registry,
        ),
    )


@pytest.mark.asyncio
async def test_invoke_without_show_usage():
    create_mock = AsyncMock(return_value="stream-result")
    azure_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create_mock))
    )

    tools = [{"name": "t1"}]
    invoker = _make_invoker(
        messages=[FakeMessage("hello")],
        azure_client=azure_client,
        tools=tools,
    )

    result = await invoker.invoke()
    assert result == "stream-result"
    assert create_mock.await_count == 1
    called_kwargs = create_mock.await_args.kwargs
    assert called_kwargs["base_param"] == "value"
    assert called_kwargs["model"] == "test-model"
    assert called_kwargs["stream"] is True
    assert called_kwargs["messages"] == [{"role": "user", "content": "hello"}]
    assert called_kwargs["tools"] == tools
    assert "stream_options" not in called_kwargs


@pytest.mark.asyncio
async def test_invoke_with_show_usage_true():
    create_mock = AsyncMock(return_value="stream-result")
    azure_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create_mock))
    )

    tools = [{"name": "t2"}]
    invoker = _make_invoker(
        messages=[FakeMessage("hello2")],
        azure_client=azure_client,
        tools=tools,
        show_usage=True,
    )

    result = await invoker.invoke()
    assert result == "stream-result"
    assert create_mock.await_count == 1
    called_kwargs = create_mock.await_args.kwargs
    assert called_kwargs["stream_options"] == {"include_usage": True}
    assert called_kwargs["tools"] == tools
    assert called_kwargs["messages"] == [{"role": "user", "content": "hello2"}]
    assert called_kwargs["stream"] is True


@pytest.mark.asyncio
async def test_invoke_propagates_exceptions():
    create_mock = AsyncMock(side_effect=RuntimeError("upstream failure"))
    azure_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create_mock))
    )

    invoker = _make_invoker(
        messages=[FakeMessage("oops")],
        azure_client=azure_client,
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


@pytest.mark.asyncio
async def test_invoke_bad_request_retries_after_recovery():
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
    invoker = _make_invoker(
        messages=messages,
        azure_client=azure_client,
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

    invoker = _make_invoker(
        messages=[FakeMessage("hello")],
        azure_client=azure_client,
        chat_completion_recovery_policies=[policy],
    )

    with pytest.raises(openai.BadRequestError):
        await invoker.invoke()

    assert create_mock.await_count == 1
