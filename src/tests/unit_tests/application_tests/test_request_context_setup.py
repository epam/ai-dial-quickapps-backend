"""Tests for _RequestContextSetup — verifying context fields are set on all request paths.

The SDK request is read by ``CompletionInputs.from_request``; ``setup_context`` only
sees the resulting inputs. Each test drives both so a request field is checked all
the way through to the context.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aidial_sdk.chat_completion import Request
from aidial_sdk.chat_completion.request import Function, StaticFunction, StaticTool, Tool
from aidial_sdk.deployment.configuration import ConfigurationRequest

from quickapp.core.application import CompletionInputs, _RequestContext
from quickapp.core.application._proxy_settings import ProxySettings
from quickapp.core.application._request_context_setup import _RequestContextSetup
from tests.unit_tests.common.common import create_app_configuration

_PATCH_MODEL_VALIDATE = patch(
    "quickapp.core.application._completion_inputs.ApplicationConfig.model_validate",
    return_value=create_app_configuration([]),
)


class _Setup:
    """Bundles the setup under test with the context it writes to."""

    def __init__(self, proxy_settings: ProxySettings | None = None) -> None:
        self.context = _RequestContext()
        context_provider = MagicMock()
        context_provider.get.return_value = self.context
        config_resolver = MagicMock()
        config_resolver.resolve_config.return_value = MagicMock()
        messages_setup = MagicMock()
        messages_setup.extract_tool_calls = MagicMock(return_value=[])
        messages_setup.run_transformers = AsyncMock(return_value=[])
        self.__language_header = (proxy_settings or ProxySettings()).language_header
        self.__setup = _RequestContextSetup(
            context_provider=context_provider,
            config_resolver=config_resolver,
            messages_setup=messages_setup,
        )

    async def setup_context(self, request: MagicMock) -> None:
        with _PATCH_MODEL_VALIDATE:
            inputs = await CompletionInputs.from_request(
                request, language_header=self.__language_header
            )
        await self.__setup.setup_context(inputs)


def _make_setup(
    proxy_settings: ProxySettings | None = None,
) -> tuple[_Setup, _RequestContext]:
    setup = _Setup(proxy_settings)
    return setup, setup.context


def _make_chat_request(headers: dict | None = None) -> MagicMock:
    request = MagicMock(spec=Request)
    request.api_key = "test-key"
    request.bearer_token = "test-bearer"
    request.messages = []
    request.response_format = None
    request.tool_choice = None
    request.tools = None
    request.headers = headers or {}
    request.request_dial_application_properties = AsyncMock(return_value={})
    return request


def _make_config_request() -> MagicMock:
    request = MagicMock(spec=ConfigurationRequest)
    request.api_key = "test-key"
    request.bearer_token = None
    request.request_dial_application_properties = AsyncMock(return_value={})
    return request


@pytest.mark.asyncio
async def test_chat_request_sets_client_channel_id_from_header():
    setup, context = _make_setup()
    request = _make_chat_request(headers={"X-DIAL-CLIENT-CHANNEL-ID": "ch-123"})
    await setup.setup_context(request)
    assert context.client_channel_id == "ch-123"


@pytest.mark.asyncio
async def test_chat_request_sets_client_channel_id_none_when_no_header():
    setup, context = _make_setup()
    request = _make_chat_request(headers={})
    await setup.setup_context(request)
    assert context.client_channel_id is None


@pytest.mark.asyncio
async def test_configuration_request_sets_client_channel_id_none():
    setup, context = _make_setup()
    request = _make_config_request()
    await setup.setup_context(request)
    assert context.client_channel_id is None


@pytest.mark.asyncio
async def test_chat_request_sets_bearer_from_request_token():
    setup, context = _make_setup()
    request = _make_chat_request(headers={})
    await setup.setup_context(request)

    assert context.bearer is not None
    assert context.bearer.get_secret_value() == "test-bearer"


@pytest.mark.asyncio
async def test_configuration_request_sets_bearer_none():
    setup, context = _make_setup()
    request = _make_config_request()
    await setup.setup_context(request)

    assert context.bearer is None


@pytest.mark.asyncio
async def test_chat_request_handles_missing_bearer_token():
    setup, context = _make_setup()
    request = _make_chat_request(headers={})
    request.bearer_token = None
    await setup.setup_context(request)

    assert context.bearer is None


def test_extra_tools_defaults_to_empty_list():
    ctx = _RequestContext()
    assert ctx.extra_tools == []


def test_extra_tools_setter_stores_tools():
    ctx = _RequestContext()
    tool = Tool(type="function", function=Function(name="my_tool"))
    ctx.extra_tools = [tool]
    assert len(ctx.extra_tools) == 1
    assert ctx.extra_tools[0].function.name == "my_tool"


def test_extra_tools_setter_raises_on_double_set():
    ctx = _RequestContext()
    ctx.extra_tools = []
    with pytest.raises(RuntimeError, match="already set"):
        ctx.extra_tools = []


@pytest.mark.asyncio
async def test_setup_context_extracts_tool_type_tools_from_request():
    setup, context = _make_setup()
    request = _make_chat_request()
    request.tools = [Tool(type="function", function=Function(name="ext_tool"))]
    await setup.setup_context(request)
    assert len(context.extra_tools) == 1
    assert context.extra_tools[0].function.name == "ext_tool"


@pytest.mark.asyncio
async def test_setup_context_excludes_static_tool_from_extra_tools():
    setup, context = _make_setup()
    request = _make_chat_request()
    tool = Tool(type="function", function=Function(name="ext_tool"))
    static = StaticTool(type="static_function", static_function=StaticFunction(name="srv_tool"))
    request.tools = [tool, static]
    await setup.setup_context(request)
    assert len(context.extra_tools) == 1
    assert context.extra_tools[0].function.name == "ext_tool"


@pytest.mark.asyncio
async def test_setup_context_leaves_extra_tools_empty_when_request_tools_none():
    setup, context = _make_setup()
    request = _make_chat_request()
    request.tools = None
    await setup.setup_context(request)
    assert context.extra_tools == []


@pytest.mark.asyncio
async def test_setup_context_does_not_set_extra_tools_for_configuration_request():
    setup, context = _make_setup()
    request = _make_config_request()
    await setup.setup_context(request)
    assert context.extra_tools == []


@pytest.mark.asyncio
async def test_chat_request_sets_accept_language_from_default_header():
    setup, context = _make_setup()
    request = _make_chat_request(headers={"accept-language": "fr"})
    await setup.setup_context(request)
    assert context.accept_language == "fr"


@pytest.mark.asyncio
async def test_chat_request_sets_accept_language_none_when_header_absent():
    setup, context = _make_setup()
    request = _make_chat_request(headers={})
    await setup.setup_context(request)
    assert context.accept_language is None


@pytest.mark.asyncio
async def test_chat_request_reads_accept_language_from_custom_header(monkeypatch):
    monkeypatch.setenv("PROXY_LANGUAGE_HEADER", "x-custom-locale")
    setup, context = _make_setup(proxy_settings=ProxySettings())
    request = _make_chat_request(headers={"x-custom-locale": "de"})
    await setup.setup_context(request)
    assert context.accept_language == "de"


@pytest.mark.asyncio
async def test_configuration_request_does_not_set_accept_language():
    setup, context = _make_setup()
    request = _make_config_request()
    await setup.setup_context(request)
    assert context.accept_language is None
