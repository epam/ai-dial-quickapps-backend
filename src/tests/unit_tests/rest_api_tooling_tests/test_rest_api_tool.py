import unittest
from unittest.mock import patch, MagicMock, AsyncMock

from aidial_client.types.chat.response import Attachment
from aidial_sdk.chat_completion import Stage
from fastapi_injector import Injected
from httpx import QueryParams
from injector import Binder, InstanceProvider
from parameterized import parameterized
from pydantic import SecretStr
from starlette.testclient import TestClient

from quickapp.common import  StagedBaseTool, DIAL_BEARER, DIAL_API_KEY
from quickapp.common.dial_settings import DialSettings
from quickapp.config.application import ApplicationConfig
from quickapp.config.tools.base import OpenAiToolConfig, OpenAiToolFunction, OpenAiToolFunctionParameters
from quickapp.config.tools.rest_api import RestApiTool, RestApiEndpointMethodInfo, RestApiEndpointSimpleTypeParam, \
    RestApiEndpointHeaderParamInfo, ToolEndpointParamType
from quickapp.config.toolsets.authorization import BearerAuthorization
from quickapp.config.toolsets.rest_api import RestApiToolSet
from quickapp.rest_api_tooling import RestApiToolingModule
from tests.unit_tests.common import create_test_app
from tests.unit_tests.common.common import create_app_configuration


class TestWebApiToolV2(unittest.IsolatedAsyncioTestCase):

    @parameterized.expand([
        (
            "get",
            "https://auth@abc.example.com:2020/index"
        )
    ])
    @patch("httpx.AsyncClient")
    async def test_web_api_tool_2_make_correct_http_call(self, request_method, url, mock_async_client):
        mock_stage = MagicMock(spec=Stage)
        response_data = {
                    "text": '{"some_key":"some value"}',
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
            tools=[
                RestApiTool(
                    rest_api_method_info=RestApiEndpointMethodInfo(
                        method_url=url,
                        method_type=request_method),
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
                                            type=ToolEndpointParamType.query,
                                            key="query_key"
                                        )
                                    )

                                },
                                type="object")
                    ))
                )
            ]
        )


        def configure(binder: Binder):
            binder.bind(DialSettings, DialSettings(url="https://core"))
            binder.bind(DIAL_BEARER, to=InstanceProvider(SecretStr("some_token")))
            binder.bind(DIAL_API_KEY, SecretStr("some_api_key"))
            # binder.bind(AttachmentService, mock_dial_attachment_service)
            binder.bind(Stage, to=mock_stage)
            binder.bind(
                ApplicationConfig,
                to=create_app_configuration([rest_api_toolset])
            )

        app = create_test_app([RestApiToolingModule, configure])

        @app.get("/")
        async def get_method(tools: list[StagedBaseTool] = Injected(list[StagedBaseTool])):
            self.assertEqual(len(tools), 1)
            tool = tools[0]

            result = await tool.arun("call-1", None, **{"query_key": "query_value"})

            # Validate core completion result properties without asserting on auto-generated attachment filenames
            self.assertEqual(result.tool_call_id, "call-1")
            self.assertEqual(result.content, '{"some_key":"some value"}')
            self.assertEqual(result.content_type, "application/json")
            self.assertIsNotNone(result.attachments)
            self.assertEqual(len(result.attachments), 1)
            self.assertIsInstance(result.attachments[0], Attachment)
            self.assertEqual(result.attachments[0].type, "application/json")
            self.assertEqual(result.attachments[0].data, '{"some_key":"some value"}')

            return {"message": "success"}

        client = TestClient(app)
        response = client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"message": "success"})

        expected_request_data = {
            "url": url,
            "method": request_method,
            "params": QueryParams('query_key=query_value'),
        }

        actual_request_data = (
            mock_async_client.return_value.__aenter__.return_value.request.call_args[1]
        )

        self.assertEqual(expected_request_data["url"], actual_request_data["url"])
        self.assertEqual(expected_request_data["params"], actual_request_data["params"])
        self.assertEqual(expected_request_data["method"].lower(), actual_request_data["method"].lower())
        self.assertIn("Authorization", actual_request_data["headers"])
        self.assertEqual("Bearer test_token", actual_request_data["headers"]["Authorization"])
