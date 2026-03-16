from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from quickapp.agent.assistant_invoker import AssistantInvoker


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
        self.name = "test-model"

class DummyOrchestrator:
    def __init__(self):
        self.deployment = DummyDeployment()

class DummyConfig:
    def __init__(self):
        self.orchestrator = DummyOrchestrator()

@pytest.fixture
def passthrough_filter():
    f = Mock()
    f.transform.side_effect = lambda messages: messages
    return f


@pytest.mark.asyncio
async def test_invoke_without_show_usage(passthrough_filter):
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
        pre_invocation_transformers=[passthrough_filter],
        presentation_settings=_presentation_settings(False),
        agent_settings=_agent_settings(),
        forwarded_headers=None
    )

    result = await invoker.invoke()
    assert result == "stream-result"
    assert create_mock.await_count == 1
    # create is called with kwargs only (no positional args)
    assert create_mock.await_args.args == ()
    called_kwargs = create_mock.await_args.kwargs
    # base param merged with payload keys
    assert called_kwargs["base_param"] == "value"
    assert called_kwargs["model"] == "test-model"
    assert called_kwargs["stream"] is True
    assert called_kwargs["messages"] == [{"role": "user", "content": "hello"}]
    assert called_kwargs["tools"] is tools
    # stream_options must NOT be present when show_usage_statistics is False
    assert "stream_options" not in called_kwargs

@pytest.mark.asyncio
async def test_invoke_with_show_usage_true(passthrough_filter):
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
        pre_invocation_transformers=[passthrough_filter],
        response_format=None,
        presentation_settings=_presentation_settings(True),
        agent_settings=_agent_settings(),
        forwarded_headers=None
    )

    result = await invoker.invoke()
    assert result == "stream-result"
    assert create_mock.await_count == 1
    called_kwargs = create_mock.await_args.kwargs
    # stream_options should be present and include_usage True
    assert "stream_options" in called_kwargs
    assert called_kwargs["stream_options"] == {"include_usage": True}
    # other keys still correct
    assert called_kwargs["tools"] is tools
    assert called_kwargs["messages"] == [{"role": "user", "content": "hello2"}]
    assert called_kwargs["stream"] is True

@pytest.mark.asyncio
async def test_invoke_propagates_exceptions(passthrough_filter):
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
        pre_invocation_transformers=[passthrough_filter],
        response_format=None,
        presentation_settings=_presentation_settings(False),
        agent_settings=_agent_settings(),
        forwarded_headers=None,
    )

    with pytest.raises(RuntimeError, match="upstream failure"):
        await invoker.invoke()

    assert create_mock.await_count == 1