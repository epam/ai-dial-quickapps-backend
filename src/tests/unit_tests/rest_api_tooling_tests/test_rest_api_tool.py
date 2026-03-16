from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aidial_sdk.chat_completion import Attachment, Stage
from fastapi_injector import Injected
from httpx import QueryParams
from injector import Binder, InstanceProvider
from pydantic import SecretStr
from starlette.testclient import TestClient

from quickapp.common import StagedBaseTool, DIAL_BEARER, DIAL_API_KEY
from quickapp.common.abstract.base_tool_argument_transformer import ToolArgumentTransformer
from quickapp.common.dial_settings import DialSettings
from quickapp.config.application import ApplicationConfig
from quickapp.config.tools.base import (
    OpenAiToolConfig,
    OpenAiToolFunction,
    OpenAiToolFunctionParameters,
)
from quickapp.config.tools.rest_api import (
    ResponseAsAttachmentConfig,
    RestApiTool,
    RestApiEndpointMethodInfo,
    RestApiEndpointSimpleTypeParam,
    RestApiEndpointHeaderParamInfo,
    ToolEndpointParamType,
)
from quickapp.config.toolsets.authorization import BearerAuthorization
from quickapp.config.toolsets.rest_api import RestApiToolSet
from quickapp.common import ForwardedHeaders
from quickapp.dial_core_services.attachment_service import AttachmentService
from quickapp.rest_api_tooling import RestApiToolingModule
from tests.unit_tests.common import create_test_app
from tests.unit_tests.common.common import create_app_configuration


def _make_rest_api_tool(url: str, method: str, **tool_kwargs) -> RestApiTool:
    return RestApiTool(
        rest_api_method_info=RestApiEndpointMethodInfo(
            method_url=url, method_type=method
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
            )
        ),
        **tool_kwargs,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("request_method,url", [("get", "https://auth@abc.example.com:2020/index")])
@patch("httpx.AsyncClient")
async def test_web_api_tool_2_make_correct_http_call(
    mock_async_client, request_method, url
):
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
        binder.bind(Stage, to=mock_stage)
        binder.bind(ApplicationConfig, to=create_app_configuration([rest_api_toolset]))
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

    actual_request_data = (
        mock_async_client.return_value.__aenter__.return_value.request.call_args[1]
    )

    assert expected_request_data["url"] == actual_request_data["url"]
    assert expected_request_data["params"] == actual_request_data["params"]
    assert (
        expected_request_data["method"].lower() == actual_request_data["method"].lower()
    )
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

    mock_dial_attachment_service.upload_attachment_to_core = AsyncMock(
        side_effect=mock_upload
    )

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
                "get",
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

    mock_dial_attachment_service.upload_attachment_to_core = AsyncMock(
        side_effect=mock_upload
    )

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
                "get",
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

    mock_dial_attachment_service.upload_attachment_to_core = AsyncMock(
        side_effect=mock_upload
    )

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
        tools=[_make_rest_api_tool(url, "get")],
    )

    def configure(binder: Binder):
        binder.bind(DialSettings, DialSettings(url="https://core"))
        binder.bind(DIAL_BEARER, to=InstanceProvider(SecretStr("some_token")))
        binder.bind(DIAL_API_KEY, SecretStr("some_api_key"))
        binder.bind(AttachmentService, mock_dial_attachment_service)
        binder.bind(Stage, to=mock_stage)
        binder.bind(ApplicationConfig, to=create_app_configuration([rest_api_toolset]))
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
    mock_async_client.return_value.__aenter__.return_value.request.return_value = (
        mock_response
    )

    rest_api_toolset = RestApiToolSet(
        name="rest-api",
        authorization=BearerAuthorization(token="test_token"),
        tools=[_make_rest_api_tool(url, "get")],
    )

    forwarded = {"X-Request-Id": "req-123", "X-Custom-Header": "custom-value"}

    def configure(binder: Binder):
        binder.bind(DialSettings, DialSettings(url="https://core"))
        binder.bind(DIAL_BEARER, to=InstanceProvider(SecretStr("some_token")))
        binder.bind(DIAL_API_KEY, SecretStr("some_api_key"))
        binder.bind(Stage, to=mock_stage)
        binder.bind(ApplicationConfig, to=create_app_configuration([rest_api_toolset]))
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

    actual_headers = (
        mock_async_client.return_value.__aenter__.return_value.request.call_args[1][
            "headers"
        ]
    )
    assert "X-Request-Id" in actual_headers
    assert actual_headers["X-Request-Id"] == "req-123"
    assert "X-Custom-Header" in actual_headers
    assert actual_headers["X-Custom-Header"] == "custom-value"
