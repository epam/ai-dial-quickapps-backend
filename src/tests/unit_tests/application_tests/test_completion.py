from types import SimpleNamespace
from typing import Mapping
from unittest.mock import Mock

import fastapi
import pytest
from aidial_sdk.chat_completion import Request, Message, Role
from httpx import HTTPError
from pydantic import StrictStr

import quickapp.application._quick_app_completion as quick_app_completion
from quickapp.application._messages_setup import _MessagesSetup
from quickapp.application._request_context import _RequestContext
from quickapp.application._request_context_setup import _RequestContextSetup
from quickapp.common.exceptions import OrchestratorExceedMaxIterationsException
from quickapp.config.config_template_resolver import ConfigResolver


class FakeChoice:
    def __init__(self):
        self.contents = []

    def append_content(self, content: str):
        # only append actual string content (ignore mocks/other objects)
        if isinstance(content, str):
            self.contents.append(content)

    def create_stage(self, name: str):
        # synchronous context manager used inside async method
        class CM:
            def __enter__(inner):
                return self

            def __exit__(inner, exc_type, exc, tb):
                return False

        return CM()


class FakeResponse:
    def __init__(self, choice: FakeChoice):
        self._choice = choice

    def create_single_choice(self):
        # synchronous context manager used inside async method
        class CM:
            def __enter__(inner):
                return self._choice

            def __exit__(inner, exc_type, exc, tb):
                return False

        return CM()


class FakeBinder:
    def __init__(self, has_binding=False):
        self._has_binding = has_binding

    def has_explicit_binding_for(self, t):
        return self._has_binding


class FakeInjector:
    def __init__(self, mapping, has_binding=False):
        self._map = mapping
        self.binder = FakeBinder(has_binding)

    def get(self, cls):
        return self._map[cls]


@pytest.fixture(autouse=True)
def patch_invoke_initializers(monkeypatch):
    # make invoke_initializers a no-op async function
    async def _noop(injector, itype):
        return None

    monkeypatch.setattr(quick_app_completion, "invoke_initializers", _noop)
    yield


# Module-level reusable valid app properties stub.
# Accepts arbitrary args so it can be used whether called as bound method or plain function.
async def valid_app_props(*args, **kwargs):
    return {
        "orchestrator": {
            "type": "default",
            "deployment": {"id": "default-deployment", "name": "default"},
            "system_prompt": {"type": "custom", "content": "You are a helpful assistant.", "variables": {}},
        },
        "contexts": [],
        "tool_sets": [],
    }





@pytest.fixture
def make_request_completion():
    def _make(orchestrator=None, api_key="k", has_binding=True, extra_mapping=None):
        request = Request(api_key_secret=StrictStr(api_key), messages=[Message(content="123", role=Role.USER), Message(content="456", role=Role.USER)], deployment_id=StrictStr("default-deployment"),
                          headers={"1":"2"}, original_request=fastapi.Request(scope={"type": "http"}))
        request.request_dial_application_properties = valid_app_props

        init_handler = SimpleNamespace(handle_initialization_errors=lambda: None)

        request_context = _RequestContext()
        provider = SimpleNamespace(get=lambda: request_context)

        config_resolver = SimpleNamespace(resolve_config=lambda cfg: cfg)
        messages_setup = _MessagesSetup([])

        request_context_setup = _RequestContextSetup(
            context_provider=provider,
            config_resolver=config_resolver,
            messages_setup=messages_setup,
        )

        mapping = {
            quick_app_completion._InitializationErrorHandler: init_handler,
            _RequestContext: request_context,
            _RequestContextSetup: request_context_setup,
            ConfigResolver: config_resolver,
            quick_app_completion.PerformanceTimer: Mock(),
        }
        if orchestrator is not None:
            mapping[quick_app_completion.Orchestrator] = orchestrator
        if extra_mapping:
            mapping.update(extra_mapping)

        injector = FakeInjector(mapping, has_binding=has_binding)
        # pass resolver as second constructor argument
        completion = quick_app_completion._QuickAppCompletion(injector)
        return request, completion, injector

    return _make


@pytest.mark.asyncio
async def test_chat_completion_success(make_request_completion):
    # Arrange
    choice = FakeChoice()
    response = FakeResponse(choice)

    orchestrator_called = {"count": 0}

    class OrchestratorFake:
        async def invoke(self):
            orchestrator_called["count"] += 1

    request, completion, _ = make_request_completion(OrchestratorFake(), api_key="dummy-key")

    # Act
    await completion.chat_completion(request, response)

    # Assert
    assert orchestrator_called["count"] == 1
    assert choice.contents == []


@pytest.mark.asyncio
async def test_chat_completion_orchestrator_exceed_exception(make_request_completion):
    # Arrange
    choice = FakeChoice()
    response = FakeResponse(choice)

    class OrchRaise:
        async def invoke(self):
            raise OrchestratorExceedMaxIterationsException()

    request, completion, _ = make_request_completion(OrchRaise(), api_key="k")

    # Act
    await completion.chat_completion(request, response)

    # Assert
    assert any("Agent stopped due to max iterations." in c for c in choice.contents)


@pytest.mark.asyncio
async def test_chat_completion_generic_exception_appends_generic_message(make_request_completion):
    # Arrange
    choice = FakeChoice()
    response = FakeResponse(choice)

    class OrchRaise:
        async def invoke(self):
            raise ValueError("boom")

    request, completion, _ = make_request_completion(OrchRaise(), api_key="k")

    # Act
    await completion.chat_completion(request, response)

    # Assert
    assert any("Something went wrong with the execution of your request" in c for c in choice.contents)


@pytest.mark.asyncio
async def test_configuration_no_binding_returns_empty_response(make_request_completion):
    # Arrange: binder.has_explicit_binding_for -> False
    request, completion, _ = make_request_completion(None, api_key="k", has_binding=False)

    # Act
    resp = await completion.configuration(request)

    # Assert
    assert isinstance(resp, quick_app_completion.ConfigurationResponse)


@pytest.mark.asyncio
async def test_configuration_with_binding_returns_config_response(make_request_completion, monkeypatch):
    # Arrange
    fake_configs = ["cfg1", "cfg2"]
    extra = {list[quick_app_completion.Configuration]: fake_configs}
    request, completion, _ = make_request_completion(None, api_key="k", has_binding=True, extra_mapping=extra)

    # monkeypatch Configuration.from_list_of_configurations to return object with to_configuration_response
    class FakeConfigured:
        def to_configuration_response(self):
            return {"ok": True}

    monkeypatch.setattr(quick_app_completion.Configuration, "from_list_of_configurations", staticmethod(lambda cfgs: FakeConfigured()))

    # Act
    resp = await completion.configuration(request)

    # Assert
    assert resp == {"ok": True}


@pytest.mark.asyncio
async def test_chat_completion_http_error_appends_message(make_request_completion):
    # Arrange
    choice = FakeChoice()
    response = FakeResponse(choice)

    class OrchRaise:
        async def invoke(self):
            raise HTTPError("http failure occurred")

    request, completion, _ = make_request_completion(OrchRaise(), api_key="k")

    # Act
    await completion.chat_completion(request, response)

    # Assert
    assert any("http failure occurred" in c for c in choice.contents)


@pytest.mark.asyncio
async def test_chat_completion_openai_internal_server_error_appends_formatted_message(make_request_completion, monkeypatch):
    # Arrange
    choice = FakeChoice()
    response = FakeResponse(choice)

    class OpenAIInternalError(Exception):
        def __init__(self, message="internal", status_code=500, request_obj="req"):
            super().__init__(message)
            self.message = message
            self.status_code = status_code
            self.request = request_obj

    monkeypatch.setattr(quick_app_completion.openai, "InternalServerError", OpenAIInternalError, raising=False)

    class OrchRaise:
        async def invoke(self):
            raise OpenAIInternalError("upstream internal error", 502, "REQUEST_OBJ")

    request, completion, _ = make_request_completion(OrchRaise(), api_key="k")

    # Act
    await completion.chat_completion(request, response)

    # Assert - check that message, status code and request representation are included
    assert any("upstream internal error" in c and "502" in c and "REQUEST_OBJ" in c for c in choice.contents)


@pytest.mark.asyncio
async def test_chat_completion_sets_context_messages_when_request_is_request(make_request_completion, monkeypatch):
    # Arrange: treat SimpleNamespace instances as Request so isinstance check passes
    monkeypatch.setattr(quick_app_completion, "Request", SimpleNamespace, raising=False)

    choice = FakeChoice()
    response = FakeResponse(choice)

    # Create request via fixture (no orchestrator needed — we only need __setup_request_context to run)
    request, completion, injector = make_request_completion(None, api_key="k")

    # Act
    await completion.chat_completion(request, response)

    # Assert: inspect the request context from the injector
    msgs = list(injector.get(_RequestContext).messages)

    assert len(msgs) == 2
    assert msgs[0].content == "123"
    assert msgs[1].content == "456"