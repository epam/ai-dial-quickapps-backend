from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from aidial_client import AsyncDial
from aidial_sdk.chat_completion import Attachment, Stage
from fastapi_injector import Injected
from httpx import QueryParams
from injector import Binder, Injector, InstanceProvider
from pydantic import SecretStr
from starlette.testclient import TestClient

from quickapp.common import DIAL_API_KEY, DIAL_BEARER, ForwardedHeaders, StagedBaseTool
from quickapp.common.abstract.base_tool_argument_transformer import ToolArgumentTransformer
from quickapp.common.dial_settings import DialSettings
from quickapp.config.application import ApplicationConfig, StageDisplayLevel
from quickapp.config.tools.base import (
    BaseOpenAITool,
    OpenAiToolConfig,
    OpenAiToolFunction,
    OpenAiToolFunctionParameters,
)
from quickapp.config.tools.rest_api import (
    ResponseAsAttachmentConfig,
    RestApiEndpointHeaderParamInfo,
    RestApiEndpointMethodInfo,
    RestApiEndpointSimpleTypeParam,
    RestApiTool,
    ToolEndpointInfoMethodType,
    ToolEndpointParamType,
)
from quickapp.config.tools.tool_fallback import ContinueStrategyModel, ToolFallbackConfig
from quickapp.config.toolsets.authorization import BearerAuthorization
from quickapp.config.toolsets.rest_api import RestApiToolSet
from quickapp.dial_core_services.attachment_service import AttachmentService
from quickapp.rest_api_tooling import RestApiToolingModule
from quickapp.rest_api_tooling._rest_api_stage_wrapper import _RestApiStageWrapper
from quickapp.rest_api_tooling._rest_api_tool_error_exception import RestApiToolErrorException
from tests.unit_tests.common import create_test_app
from tests.unit_tests.common.common import create_app_configuration


def _make_rest_api_tool(
    url: str, method: ToolEndpointInfoMethodType, name: str = 'test_function', **tool_kwargs
) -> RestApiTool:
    return RestApiTool(
        rest_api_method_info=RestApiEndpointMethodInfo(method_url=url, method_type=method),
        open_ai_tool=OpenAiToolConfig(
            function=OpenAiToolFunction(
                name=name,
                description="Test function",
                parameters=OpenAiToolFunctionParameters(
                    properties={
                        "query_key": RestApiEndpointSimpleTypeParam(
                            type="string",
                            description="Query key",
                            parameter_info=RestApiEndpointHeaderParamInfo(
                                type=ToolEndpointParamType.query, key="query_key"
                            ),
                        )
                    },
                    type="object",
                ),
            )
        ),
        **tool_kwargs,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "request_method,url",
    [(ToolEndpointInfoMethodType.get, "https://auth@abc.example.com:2020/index")],
)
@patch("httpx.AsyncClient")
async def test_web_api_tool_2_make_correct_http_call(mock_async_client, request_method, url):
    mock_stage = MagicMock(spec=Stage)
    response_data = {
        "text": '{"some_key":"some value"}',
        "headers": {"Content-Type": "application/json"},
    }
    mock_response = AsyncMock(**response_data)
    mock_response.raise_for_status = MagicMock()
    mock_async_client.return_value.__aenter__.return_value.request.return_value = mock_response

    rest_api_toolset = RestApiToolSet(
        name="rest-api",
        authorization=BearerAuthorization(token="test_token"),
        tools=[
            RestApiTool(
                rest_api_method_info=RestApiEndpointMethodInfo(
                    method_url=url, method_type=request_method
                ),
                open_ai_tool=OpenAiToolConfig(
                    function=OpenAiToolFunction(
                        name="test_function",
                        description="Test function",
                        parameters=OpenAiToolFunctionParameters(
                            properties={
                                "query_key": RestApiEndpointSimpleTypeParam(
                                    type="string",
                                    description="Query key",
                                    parameter_info=RestApiEndpointHeaderParamInfo(
                                        type=ToolEndpointParamType.query, key="query_key"
                                    ),
                                )
                            },
                            type="object",
                        ),
                    ),
                ),
            )
        ],
    )

    def configure(binder: Binder):
        binder.bind(DialSettings, DialSettings(url="https://core"))
        binder.bind(DIAL_BEARER, to=InstanceProvider(SecretStr("some_token")))
        binder.bind(DIAL_API_KEY, SecretStr("some_api_key"))
        binder.bind(AsyncDial, to=InstanceProvider(MagicMock(spec=AsyncDial)))
        binder.bind(Stage, to=mock_stage)
        binder.bind(ApplicationConfig, to=create_app_configuration([rest_api_toolset]))
        binder.bind(StageDisplayLevel, to=InstanceProvider(StageDisplayLevel.INFO))
        binder.bind(ForwardedHeaders, to=InstanceProvider(None))
        binder.multibind(list[ToolArgumentTransformer], to=[])

    app = create_test_app([RestApiToolingModule, configure])

    @app.get("/")
    async def get_method(tools: list[StagedBaseTool] = Injected(list[StagedBaseTool])):
        assert len(tools) == 1
        tool = tools[0]

        result = await tool.arun("call-1", None, **{"query_key": "query_value"})

        # With default response_as_attachment (None/disabled), no attachment is created
        assert result.tool_call_id == "call-1"
        assert result.content == '{"some_key":"some value"}'
        assert result.content_type == "application/json"
        assert result.attachments == []

        return {"message": "success"}

    client = TestClient(app)
    response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {"message": "success"}

    expected_request_data = {
        "url": url,
        "method": request_method,
        "params": QueryParams('query_key=query_value'),
    }

    actual_request_data = mock_async_client.return_value.__aenter__.return_value.request.call_args[
        1
    ]

    assert expected_request_data["url"] == actual_request_data["url"]
    assert expected_request_data["params"] == actual_request_data["params"]
    assert expected_request_data["method"].lower() == actual_request_data["method"].lower()
    assert "authorization" in actual_request_data["headers"]
    assert "Bearer test_token" == actual_request_data["headers"]["authorization"]


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_response_as_attachment_enabled_creates_attachment(mock_async_client):
    url = "https://example.com/api"
    mock_stage = MagicMock(spec=Stage)
    mock_dial_attachment_service = MagicMock(spec=AttachmentService)

    async def mock_upload(attachment):
        return attachment

    mock_dial_attachment_service.upload_attachment_to_core = AsyncMock(side_effect=mock_upload)

    response_data = {
        "text": '{"data": "value"}',
        "headers": {"Content-Type": "application/json"},
    }
    mock_response = AsyncMock(**response_data)
    mock_response.raise_for_status = MagicMock()
    mock_async_client.return_value.__aenter__.return_value.request.return_value = mock_response

    rest_api_toolset = RestApiToolSet(
        name="rest-api",
        authorization=BearerAuthorization(token="test_token"),
        tools=[
            _make_rest_api_tool(
                url,
                ToolEndpointInfoMethodType.get,
                response_as_attachment=ResponseAsAttachmentConfig(enabled=True),
            )
        ],
    )

    def configure(binder: Binder):
        binder.bind(DialSettings, DialSettings(url="https://core"))
        binder.bind(DIAL_BEARER, to=InstanceProvider(SecretStr("some_token")))
        binder.bind(DIAL_API_KEY, SecretStr("some_api_key"))
        binder.bind(AttachmentService, mock_dial_attachment_service)
        binder.bind(Stage, to=mock_stage)
        binder.bind(ApplicationConfig, to=create_app_configuration([rest_api_toolset]))
        binder.bind(StageDisplayLevel, to=InstanceProvider(StageDisplayLevel.INFO))
        binder.bind(ForwardedHeaders, to=InstanceProvider(None))
        binder.multibind(list[ToolArgumentTransformer], to=[])

    app = create_test_app([RestApiToolingModule, configure])

    @app.get("/")
    async def get_method(tools: list[StagedBaseTool] = Injected(list[StagedBaseTool])):
        assert len(tools) == 1
        result = await tools[0].arun("call-1", None, **{"query_key": "query_value"})

        assert result.tool_call_id == "call-1"
        assert result.content == '{"data": "value"}'
        assert result.attachments is not None
        assert len(result.attachments) == 1
        assert isinstance(result.attachments[0], Attachment)
        assert result.attachments[0].type == "application/json"
        return {"message": "success"}

    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_response_as_attachment_include_body_as_content_false(mock_async_client):
    url = "https://example.com/api"
    mock_stage = MagicMock(spec=Stage)
    mock_dial_attachment_service = MagicMock(spec=AttachmentService)

    async def mock_upload(attachment):
        return attachment

    mock_dial_attachment_service.upload_attachment_to_core = AsyncMock(side_effect=mock_upload)

    response_data = {
        "text": '{"data": "value"}',
        "headers": {"Content-Type": "application/json"},
    }
    mock_response = AsyncMock(**response_data)
    mock_response.raise_for_status = MagicMock()
    mock_async_client.return_value.__aenter__.return_value.request.return_value = mock_response

    rest_api_toolset = RestApiToolSet(
        name="rest-api",
        authorization=BearerAuthorization(token="test_token"),
        tools=[
            _make_rest_api_tool(
                url,
                ToolEndpointInfoMethodType.get,
                response_as_attachment=ResponseAsAttachmentConfig(
                    enabled=True, include_body_as_content=False
                ),
            )
        ],
    )

    def configure(binder: Binder):
        binder.bind(DialSettings, DialSettings(url="https://core"))
        binder.bind(DIAL_BEARER, to=InstanceProvider(SecretStr("some_token")))
        binder.bind(DIAL_API_KEY, SecretStr("some_api_key"))
        binder.bind(AttachmentService, mock_dial_attachment_service)
        binder.bind(Stage, to=mock_stage)
        binder.bind(ApplicationConfig, to=create_app_configuration([rest_api_toolset]))
        binder.bind(StageDisplayLevel, to=InstanceProvider(StageDisplayLevel.INFO))
        binder.bind(ForwardedHeaders, to=InstanceProvider(None))
        binder.multibind(list[ToolArgumentTransformer], to=[])

    app = create_test_app([RestApiToolingModule, configure])

    @app.get("/")
    async def get_method(tools: list[StagedBaseTool] = Injected(list[StagedBaseTool])):
        assert len(tools) == 1
        result = await tools[0].arun("call-1", None, **{"query_key": "query_value"})

        assert result.tool_call_id == "call-1"
        assert result.content.startswith("See attached file:")
        assert len(result.attachments) == 1
        return {"message": "success"}

    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_toolset_level_response_as_attachment_propagation(mock_async_client):
    url = "https://example.com/api"
    mock_stage = MagicMock(spec=Stage)
    mock_dial_attachment_service = MagicMock(spec=AttachmentService)

    async def mock_upload(attachment):
        return attachment

    mock_dial_attachment_service.upload_attachment_to_core = AsyncMock(side_effect=mock_upload)

    response_data = {
        "text": '{"data": "value"}',
        "headers": {"Content-Type": "application/json"},
    }
    mock_response = AsyncMock(**response_data)
    mock_response.raise_for_status = MagicMock()
    mock_async_client.return_value.__aenter__.return_value.request.return_value = mock_response

    # Tool does NOT set response_as_attachment, but toolset does
    rest_api_toolset = RestApiToolSet(
        name="rest-api",
        authorization=BearerAuthorization(token="test_token"),
        response_as_attachment=ResponseAsAttachmentConfig(enabled=True),
        tools=[_make_rest_api_tool(url, ToolEndpointInfoMethodType.get)],
    )

    def configure(binder: Binder):
        binder.bind(DialSettings, DialSettings(url="https://core"))
        binder.bind(DIAL_BEARER, to=InstanceProvider(SecretStr("some_token")))
        binder.bind(DIAL_API_KEY, SecretStr("some_api_key"))
        binder.bind(AttachmentService, mock_dial_attachment_service)
        binder.bind(Stage, to=mock_stage)
        binder.bind(ApplicationConfig, to=create_app_configuration([rest_api_toolset]))
        binder.bind(StageDisplayLevel, to=InstanceProvider(StageDisplayLevel.INFO))
        binder.bind(ForwardedHeaders, to=InstanceProvider(None))
        binder.multibind(list[ToolArgumentTransformer], to=[])

    app = create_test_app([RestApiToolingModule, configure])

    @app.get("/")
    async def get_method(tools: list[StagedBaseTool] = Injected(list[StagedBaseTool])):
        assert len(tools) == 1
        result = await tools[0].arun("call-1", None, **{"query_key": "query_value"})

        assert result.tool_call_id == "call-1"
        assert result.attachments is not None
        assert len(result.attachments) == 1
        assert result.attachments[0].type == "application/json"
        return {"message": "success"}

    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_forwarded_x_headers_passed_to_rest_api_request(mock_async_client):
    """X-* headers from forwarded_headers (dict) are included in the outgoing HTTP request."""
    url = "https://example.com/api"
    mock_stage = MagicMock(spec=Stage)
    response_data = {
        "text": '{"ok": true}',
        "headers": {"Content-Type": "application/json"},
    }
    mock_response = AsyncMock(**response_data)
    mock_response.raise_for_status = MagicMock()
    mock_async_client.return_value.__aenter__.return_value.request.return_value = mock_response

    rest_api_toolset = RestApiToolSet(
        name="rest-api",
        authorization=BearerAuthorization(token="test_token"),
        tools=[_make_rest_api_tool(url, ToolEndpointInfoMethodType.get)],
    )

    forwarded = {"X-Request-Id": "req-123", "X-Custom-Header": "custom-value"}

    def configure(binder: Binder):
        binder.bind(DialSettings, DialSettings(url="https://core"))
        binder.bind(DIAL_BEARER, to=InstanceProvider(SecretStr("some_token")))
        binder.bind(DIAL_API_KEY, SecretStr("some_api_key"))
        binder.bind(AsyncDial, to=InstanceProvider(MagicMock(spec=AsyncDial)))
        binder.bind(Stage, to=mock_stage)
        binder.bind(ApplicationConfig, to=create_app_configuration([rest_api_toolset]))
        binder.bind(StageDisplayLevel, to=InstanceProvider(StageDisplayLevel.INFO))
        binder.bind(ForwardedHeaders, to=InstanceProvider(forwarded))
        binder.multibind(list[ToolArgumentTransformer], to=[])

    app = create_test_app([RestApiToolingModule, configure])

    @app.get("/")
    async def get_method(tools: list[StagedBaseTool] = Injected(list[StagedBaseTool])):
        assert len(tools) == 1
        await tools[0].arun("call-1", None, **{"query_key": "query_value"})
        return {"message": "success"}

    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200

    actual_headers = mock_async_client.return_value.__aenter__.return_value.request.call_args[1][
        "headers"
    ]
    assert "X-Request-Id" in actual_headers
    assert actual_headers["X-Request-Id"] == "req-123"
    assert "X-Custom-Header" in actual_headers
    assert actual_headers["X-Custom-Header"] == "custom-value"


def test_openai_tools_names():
    toolset_name = "rest-api-toolset"
    tool_name = "rest-tool"
    rest_api_toolset = RestApiToolSet(
        name=toolset_name,
        tools=[
            _make_rest_api_tool(
                "https://example.com/api", ToolEndpointInfoMethodType.get, name=tool_name
            )
        ],
    )

    def configure(binder: Binder):
        binder.bind(ApplicationConfig, to=create_app_configuration([rest_api_toolset]))
        binder.bind(DialSettings, DialSettings(url="https://core"))
        binder.bind(DIAL_BEARER, to=InstanceProvider(SecretStr("some_token")))
        binder.bind(DIAL_API_KEY, SecretStr("some_api_key"))
        binder.bind(AsyncDial, to=InstanceProvider(MagicMock(spec=AsyncDial)))
        binder.bind(StageDisplayLevel, to=InstanceProvider(StageDisplayLevel.INFO))
        binder.bind(ForwardedHeaders, to=InstanceProvider(None))
        binder.multibind(list[ToolArgumentTransformer], to=[])

    injector = Injector(modules=[RestApiToolingModule, configure])
    tools = injector.get(list[StagedBaseTool])

    assert len(tools) == 1
    tool_config: BaseOpenAITool = tools[0].tool_config
    assert tool_config.open_ai_tool.function.name == f"{toolset_name}_{tool_name}"


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_http_status_error_can_forward_error_message_via_fallback(mock_async_client):
    url = "https://example.com/api"
    mock_stage = MagicMock(spec=Stage)
    response = httpx.Response(
        400,
        json={"error": "Invalid API key"},
        request=httpx.Request("GET", url),
    )
    mock_response = AsyncMock(text=response.text, headers={"Content-Type": "application/json"})
    mock_response.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError(
            "bad request", request=response.request, response=response
        )
    )
    mock_async_client.return_value.__aenter__.return_value.request.return_value = mock_response

    rest_api_toolset = RestApiToolSet(
        name="rest-api",
        authorization=BearerAuthorization(token="test_token"),
        tools=[
            _make_rest_api_tool(
                url,
                ToolEndpointInfoMethodType.get,
                fallback_configuration=ToolFallbackConfig(
                    strategies=[ContinueStrategyModel(forward_tool_error_message=True)]
                ),
            )
        ],
    )

    def configure(binder: Binder):
        binder.bind(DialSettings, DialSettings(url="https://core"))
        binder.bind(DIAL_BEARER, to=InstanceProvider(SecretStr("some_token")))
        binder.bind(DIAL_API_KEY, SecretStr("some_api_key"))
        binder.bind(AsyncDial, to=InstanceProvider(MagicMock(spec=AsyncDial)))
        binder.bind(Stage, to=mock_stage)
        binder.bind(ApplicationConfig, to=create_app_configuration([rest_api_toolset]))
        binder.bind(StageDisplayLevel, to=InstanceProvider(StageDisplayLevel.INFO))
        binder.bind(ForwardedHeaders, to=InstanceProvider(None))
        binder.multibind(list[ToolArgumentTransformer], to=[])

    app = create_test_app([RestApiToolingModule, configure])

    @app.get("/")
    async def get_method(tools: list[StagedBaseTool] = Injected(list[StagedBaseTool])):
        result = await tools[0].arun("call-1", None, **{"query_key": "query_value"})
        # catch-all forwards error directly; deprecated flag has no additional effect
        assert result.content == "HTTP error 400 while calling REST API tool."
        assert result.content_type == "text/markdown"
        return {"message": "success"}

    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_http_status_error_can_append_instructions_after_forwarded_error(mock_async_client):
    url = "https://example.com/api"
    mock_stage = MagicMock(spec=Stage)
    response = httpx.Response(
        429,
        json={"detail": "Rate limit exceeded"},
        request=httpx.Request("GET", url),
    )
    mock_response = AsyncMock(text=response.text, headers={"Content-Type": "application/json"})
    mock_response.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError(
            "rate limited", request=response.request, response=response
        )
    )
    mock_async_client.return_value.__aenter__.return_value.request.return_value = mock_response

    rest_api_toolset = RestApiToolSet(
        name="rest-api",
        authorization=BearerAuthorization(token="test_token"),
        tools=[
            _make_rest_api_tool(
                url,
                ToolEndpointInfoMethodType.get,
                fallback_configuration=ToolFallbackConfig(
                    strategies=[
                        ContinueStrategyModel(
                            instructions="Wait a bit and try a different tool.",
                            forward_tool_error_message=True,
                        )
                    ]
                ),
            )
        ],
    )

    def configure(binder: Binder):
        binder.bind(DialSettings, DialSettings(url="https://core"))
        binder.bind(DIAL_BEARER, to=InstanceProvider(SecretStr("some_token")))
        binder.bind(DIAL_API_KEY, SecretStr("some_api_key"))
        binder.bind(AsyncDial, to=InstanceProvider(MagicMock(spec=AsyncDial)))
        binder.bind(Stage, to=mock_stage)
        binder.bind(ApplicationConfig, to=create_app_configuration([rest_api_toolset]))
        binder.bind(StageDisplayLevel, to=InstanceProvider(StageDisplayLevel.INFO))
        binder.bind(ForwardedHeaders, to=InstanceProvider(None))
        binder.multibind(list[ToolArgumentTransformer], to=[])

    app = create_test_app([RestApiToolingModule, configure])

    @app.get("/")
    async def get_method(tools: list[StagedBaseTool] = Injected(list[StagedBaseTool])):
        result = await tools[0].arun("call-1", None, **{"query_key": "query_value"})
        # catch-all with instructions — instructions deprecated and ignored; error forwarded
        assert result.content == "HTTP error 429 while calling REST API tool."
        return {"message": "success"}

    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200


def test_rest_api_stage_wrapper_uses_http_status_error_cause_for_debug_info():
    stage = MagicMock(spec=Stage)
    wrapper = _RestApiStageWrapper(stage=stage)
    response = httpx.Response(
        502,
        text="Gateway failure",
        request=httpx.Request("GET", "https://example.com/api"),
    )
    cause = httpx.HTTPStatusError("bad gateway", request=response.request, response=response)

    exception = RestApiToolErrorException("rest_tool", "Gateway failure")
    exception.__cause__ = cause

    output = wrapper._build_debug_info_from_exception(exception)

    assert "502" in output
    assert "Gateway failure" in output
