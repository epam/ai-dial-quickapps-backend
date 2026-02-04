from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from quickapp.agent.assistant_invoker import AssistantInvoker


# Minimal test helpers
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

@pytest.mark.asyncio
async def test_invoke_without_show_usage(monkeypatch):
    # Ensure env var is not set
    monkeypatch.delenv("SHOW_USAGE_STATISTICS", raising=False)

    # Prepare mocked azure client
    create_mock = AsyncMock(return_value="stream-result")
    azure_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create_mock))
    )

    messages_context = SimpleNamespace(messages=[FakeMessage("hello")])
    tools = [{"name": "t1"}]
    invoker = AssistantInvoker(
        tools=tools,
        config=DummyConfig(),
        messages_context=messages_context,
        choice=SimpleNamespace(),  # not used in code under test
        azure_client=azure_client,

        response_format=None
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
    assert called_kwargs["tools"] is tools
    # stream_options must NOT be present when env var unset
    assert "stream_options" not in called_kwargs

@pytest.mark.asyncio
async def test_invoke_with_show_usage_true(monkeypatch):
    monkeypatch.setenv("SHOW_USAGE_STATISTICS", "true")

    create_mock = AsyncMock(return_value="stream-result")
    azure_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create_mock))
    )

    messages_context = SimpleNamespace(messages=[FakeMessage("hello2")])
    tools = [{"name": "t2"}]
    invoker = AssistantInvoker(
        tools=tools,
        config=DummyConfig(),
        messages_context=messages_context,
        choice=SimpleNamespace(),
        azure_client=azure_client,

        response_format=None
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

# python
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "exc_body, expected_display",
    [
        ({"message": "bad request"}, "bad request"),
        ("rate limited", "rate limited"),
    ],
)
async def test_invoke_translates_openai_errors_to_invalid_request(monkeypatch, exc_body, expected_display):
    class FakeOpenAIError(Exception):
        def __init__(self, code, body):
            super().__init__(str(body))
            self.code = code
            self.body = body

    import quickapp.agent.assistant_invoker as ai_mod

    # Replace the exception types in the module so the except block matches our fake error
    monkeypatch.setattr(ai_mod, "BadRequestError", FakeOpenAIError)
    monkeypatch.setattr(ai_mod, "RateLimitError", FakeOpenAIError)

    # Make the azure client raise the fake error
    create_mock = AsyncMock(side_effect=FakeOpenAIError("ERR_CODE", exc_body))
    azure_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create_mock))
    )

    messages_context = SimpleNamespace(messages=[FakeMessage("oops")])
    invoker = AssistantInvoker(
        tools=[{"name": "t"}],
        config=DummyConfig(),
        messages_context=messages_context,
        choice=SimpleNamespace(),
        azure_client=azure_client,

        response_format=None
    )

    from aidial_sdk.exceptions import InvalidRequestError
    with pytest.raises(InvalidRequestError) as excinfo:
        await invoker.invoke()

    # Ensure the original error code and derived display message are propagated
    assert excinfo.value.message == "ERR_CODE"
    assert excinfo.value.display_message == expected_display
    assert create_mock.await_count == 1