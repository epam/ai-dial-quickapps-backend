from types import SimpleNamespace
from unittest.mock import Mock

import fastapi
import pytest
from aidial_sdk.chat_completion import Message, Request, Role
from aidial_sdk.exceptions import HTTPException as DialHTTPException
from aidial_sdk.exceptions import InvalidRequestError
from httpx import HTTPError

import quickapp.core.application._quick_app_completion as quick_app_completion
from quickapp.common.exceptions import (
    ConfigResolutionException,
    OrchestratorExceedMaxIterationsException,
)
from quickapp.config.config_template_resolver import ConfigResolver
from quickapp.core.application import _MessagesSetup, _RequestContext
from quickapp.core.application._proxy_settings import ProxySettings
from quickapp.core.application._request_context_setup import _RequestContextSetup


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
            "system_prompt": {
                "type": "custom",
                "content": "You are a helpful assistant.",
                "variables": {},
            },
        },
        "contexts": [],
        "tool_sets": [],
    }


@pytest.fixture
def make_request_completion():
    def _make(
        orchestrator=None,
        api_key="k",
        has_binding=True,
        extra_mapping=None,
        messages=None,
        config_resolver=None,
        init_handler=None,
    ):
        if messages is None:
            messages = [
                Message(content="123", role=Role.USER),
                Message(content="456", role=Role.ASSISTANT),
                Message(content="789", role=Role.USER),
            ]
        request = Request(
            api_key_secret=api_key,
            messages=messages,
            deployment_id="default-deployment",
            headers={"1": "2"},
            original_request=fastapi.Request(scope={"type": "http"}),
        )
        request.request_dial_application_properties = valid_app_props

        if init_handler is None:
            init_handler = SimpleNamespace(handle_initialization_issues=lambda: None)

        request_context = _RequestContext()
        provider = SimpleNamespace(get=lambda: request_context)

        if config_resolver is None:
            config_resolver = SimpleNamespace(resolve_config=lambda cfg: cfg)
        messages_setup = _MessagesSetup(SimpleNamespace(get=lambda: []))

        request_context_setup = _RequestContextSetup(
            context_provider=provider,
            config_resolver=config_resolver,
            messages_setup=messages_setup,
            proxy_settings=ProxySettings(),
        )

        mapping = {
            quick_app_completion._InitializationErrorHandler: init_handler,
            _RequestContext: request_context,
            _RequestContextSetup: request_context_setup,
            _MessagesSetup: messages_setup,
            ConfigResolver: config_resolver,
            quick_app_completion.PerformanceTimer: Mock(),
            quick_app_completion.ApplicationConfig: SimpleNamespace(
                orchestrator=SimpleNamespace(
                    deployment=SimpleNamespace(deployment_id="default-deployment")
                ),
                skills=None,
                contexts=[],
            ),
            list[quick_app_completion.StagedBaseTool]: [],
            quick_app_completion.AgentSkillsProvider: SimpleNamespace(get_all_skills=lambda: []),
        }
        if orchestrator is not None:
            mapping[quick_app_completion.Orchestrator] = orchestrator
        if extra_mapping:
            mapping.update(extra_mapping)

        presentation_settings = SimpleNamespace(
            show_usage_statistics=False, show_execution_time_stage=False
        )
        mapping[quick_app_completion.PresentationSettings] = presentation_settings

        injector = FakeInjector(mapping, has_binding=has_binding)
        completion = quick_app_completion._QuickAppCompletion(injector, presentation_settings)
        return request, completion, injector

    return _make


@pytest.mark.asyncio
async def test_chat_completion_success(make_request_completion):
    # Arrange
    choice = FakeChoice()
    response = FakeResponse(choice)

    orchestrator_called = {"count": 0}

    class OrchestratorFake:
        iteration_count = 1
        total_tool_calls = 0
        completion_kind = "completed"

        async def invoke(self):
            orchestrator_called["count"] += 1

    request, completion, _ = make_request_completion(OrchestratorFake(), api_key="dummy-key")

    # Act
    await completion.chat_completion(request, response)

    # Assert
    assert orchestrator_called["count"] == 1
    assert choice.contents == []


@pytest.mark.asyncio
async def test_chat_completion_orchestrator_exceed_raises_dial_error(make_request_completion):
    # Arrange
    choice = FakeChoice()
    response = FakeResponse(choice)

    class OrchRaise:
        iteration_count = 1
        total_tool_calls = 0
        completion_kind = "completed"

        async def invoke(self):
            raise OrchestratorExceedMaxIterationsException()

    request, completion, _ = make_request_completion(OrchRaise(), api_key="k")

    # Act + Assert: delivered as a DIAL protocol error, not swallowed into choice content
    with pytest.raises(DialHTTPException) as exc:
        await completion.chat_completion(request, response)

    display = exc.value.display_message
    assert display is not None
    assert "Agent stopped due to max iterations." in display
    assert choice.contents == []


@pytest.mark.asyncio
async def test_chat_completion_generic_exception_raises_generic_message(make_request_completion):
    # Arrange
    choice = FakeChoice()
    response = FakeResponse(choice)

    class OrchRaise:
        iteration_count = 1
        total_tool_calls = 0
        completion_kind = "completed"

        async def invoke(self):
            raise ValueError("boom")

    request, completion, _ = make_request_completion(OrchRaise(), api_key="k")

    # Act + Assert
    with pytest.raises(DialHTTPException) as exc:
        await completion.chat_completion(request, response)

    display = exc.value.display_message
    assert display is not None
    assert "Something went wrong with the execution of your request" in display
    assert exc.value.status_code == 500
    assert choice.contents == []


@pytest.mark.asyncio
async def test_configuration_no_binding_returns_empty_response(make_request_completion):
    # Arrange: binder.has_explicit_binding_for -> False
    request, completion, _ = make_request_completion(None, api_key="k", has_binding=False)

    # Act
    resp = await completion.configuration(request)

    # Assert
    assert isinstance(resp, quick_app_completion.ConfigurationResponse)


@pytest.mark.asyncio
async def test_configuration_with_binding_returns_config_response(
    make_request_completion, monkeypatch
):
    # Arrange
    fake_configs = ["cfg1", "cfg2"]
    extra = {list[quick_app_completion.Configuration]: fake_configs}
    request, completion, _ = make_request_completion(
        None, api_key="k", has_binding=True, extra_mapping=extra
    )

    # monkeypatch Configuration.from_list_of_configurations to return object with to_configuration_response
    class FakeConfigured:
        def to_configuration_response(self):
            return {"ok": True}

    monkeypatch.setattr(
        quick_app_completion.Configuration,
        "from_list_of_configurations",
        staticmethod(lambda cfgs: FakeConfigured()),
    )

    # Act
    resp = await completion.configuration(request)

    # Assert
    assert resp == {"ok": True}


@pytest.mark.asyncio
async def test_chat_completion_http_error_raises_safe_message(make_request_completion):
    # Arrange
    choice = FakeChoice()
    response = FakeResponse(choice)

    class OrchRaise:
        iteration_count = 1
        total_tool_calls = 0
        completion_kind = "completed"

        async def invoke(self):
            raise HTTPError("http://internal-service/secret-endpoint failure")

    request, completion, _ = make_request_completion(OrchRaise(), api_key="k")

    # Act + Assert: a user-friendly message is delivered and the raw internal URL is NOT leaked
    with pytest.raises(DialHTTPException) as exc:
        await completion.chat_completion(request, response)

    display = exc.value.display_message
    assert display is not None
    assert "http error" in display.lower()
    assert "http://internal-service" not in display
    assert choice.contents == []


@pytest.mark.asyncio
async def test_chat_completion_openai_internal_server_error_raises_safe_message(
    make_request_completion,
):
    # Arrange
    choice = FakeChoice()
    response = FakeResponse(choice)

    import httpx as _httpx
    import openai as _openai

    _request = _httpx.Request("GET", "http://internal-dial-core/api")
    _response = _httpx.Response(500, request=_request)

    class OrchRaise:
        iteration_count = 1
        total_tool_calls = 0
        completion_kind = "completed"

        async def invoke(self):
            raise _openai.InternalServerError(
                "upstream internal error", response=_response, body=None
            )

    request, completion, _ = make_request_completion(OrchRaise(), api_key="k")

    # Act + Assert: clean message delivered, raw internal details NOT exposed. An upstream
    # 500 is downgraded to 500 (never a Core-retriable status).
    with pytest.raises(DialHTTPException) as exc:
        await completion.chat_completion(request, response)

    display = exc.value.display_message
    assert display is not None
    assert "internal error" in display.lower()
    assert "http://internal-dial-core" not in display
    assert "upstream internal error" not in display
    assert exc.value.status_code == 500
    assert choice.contents == []


@pytest.mark.asyncio
async def test_chat_completion_sets_context_messages_when_request_is_request(
    make_request_completion, monkeypatch
):
    # Arrange: treat SimpleNamespace instances as Request so isinstance check passes
    monkeypatch.setattr(quick_app_completion, "Request", SimpleNamespace, raising=False)

    choice = FakeChoice()
    response = FakeResponse(choice)

    class OrchestratorFake:
        iteration_count = 1
        total_tool_calls = 0
        completion_kind = "completed"

        async def invoke(self):
            return None

    # We only need the request-context setup to run; a no-op orchestrator lets the
    # success path complete so we can inspect the resolved messages.
    request, completion, injector = make_request_completion(OrchestratorFake(), api_key="k")

    # Act
    await completion.chat_completion(request, response)

    # Assert: inspect the request context from the injector
    msgs = list(injector.get(_RequestContext).messages)

    assert len(msgs) == 3
    assert msgs[0].content == "123"
    assert msgs[1].content == "456"
    assert msgs[2].content == "789"


@pytest.mark.asyncio
async def test_chat_completion_system_prompt_failure_renders_initialization_stage(
    make_request_completion,
):
    """A system-prompt resolution failure (the only path that still raises
    `ConfigResolutionException`) routes to the *Initialization issues* handler
    instead of falling through to the generic fallback message."""
    choice = FakeChoice()
    response = FakeResponse(choice)

    def _resolve_raises(_cfg):
        raise ConfigResolutionException(
            message="bad",
            template_name="dial_rag",
            json_path="/deployment/name",
        )

    handler_calls = {"count": 0}
    init_handler = SimpleNamespace(
        handle_initialization_issues=lambda: handler_calls.__setitem__(
            "count", handler_calls["count"] + 1
        )
    )

    orchestrator_called = {"count": 0}

    class OrchestratorFake:
        async def invoke(self):
            orchestrator_called["count"] += 1

    request, completion, _ = make_request_completion(
        OrchestratorFake(),
        config_resolver=SimpleNamespace(resolve_config=_resolve_raises),
        init_handler=init_handler,
    )

    await completion.chat_completion(request, response)

    assert handler_calls["count"] == 1
    assert orchestrator_called["count"] == 0
    assert not any(
        "Something went wrong with the execution of your request" in c for c in choice.contents
    )


@pytest.mark.asyncio
async def test_chat_completion_invalid_messages_raises_invalid_request_error(
    make_request_completion,
):
    # Arrange: two consecutive user messages violate (System)? (User Assistant)* User
    choice = FakeChoice()
    response = FakeResponse(choice)

    bad_messages = [
        Message(content="a", role=Role.USER),
        Message(content="b", role=Role.USER),
    ]
    request, completion, _ = make_request_completion(None, messages=bad_messages)

    # Act + Assert: InvalidRequestError propagates past the create_single_choice
    # block so the aidial_sdk exception handler can produce HTTP 400
    with pytest.raises(InvalidRequestError) as exc:
        await completion.chat_completion(request, response)

    display = exc.value.display_message
    assert display is not None
    assert "Invalid messages array" in display
    assert "expected role 'assistant'" in display
    # The error must NOT be swallowed into the streamed choice content
    assert choice.contents == []
