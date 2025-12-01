import unittest
from unittest.mock import patch, MagicMock, AsyncMock
import pytest

from aidial_sdk.chat_completion import Stage
from fastapi_injector import Injected
from httpx import QueryParams
from injector import Binder
from parameterized import parameterized
from starlette.testclient import TestClient

from quickapp.common import CompletionResult, StagedBaseTool
from quickapp.config.application import ApplicationConfig
from quickapp.config.tools.base import OpenAiToolConfig, OpenAiToolFunction, OpenAiToolFunctionParameters
from quickapp.config.tools.rest_api import RestApiTool, RestApiEndpointMethodInfo, RestApiEndpointSimpleTypeParam, \
    RestApiEndpointHeaderParamInfo, ToolEndpointParamType
from quickapp.config.toolsets.authorization import BearerAuthorization
from quickapp.config.toolsets.rest_api import RestApiToolSet
from quickapp.rest_api_tooling import RestApiToolingModule
from tests.common import create_test_app
from tests.common.common import create_app_configuration, build_tool_expected_result


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
            self.assertEqual(result, CompletionResult(tool_call_id="call-1", content='{"some_key":"some value"}', content_type="application/json", attachments=None))
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
