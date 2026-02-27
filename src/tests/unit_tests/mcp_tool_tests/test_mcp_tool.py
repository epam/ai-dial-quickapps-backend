import base64
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, AsyncMock

from aidial_sdk.chat_completion import Attachment, Stage
from fastapi_injector import Injected
from injector import Binder, Injector, InstanceProvider
from mcp.types import ImageContent, EmbeddedResource, TextResourceContents, BlobResourceContents
from pydantic import AnyUrl, SecretStr
from starlette.testclient import TestClient

from quickapp.common import CompletionResult, DIAL_API_KEY, StagedBaseTool, DIAL_BEARER
from quickapp.common.abstract.base_tool_argument_transformer import ToolArgumentTransformer
from quickapp.common.base_initializer import CompletionInitializer
from quickapp.common.dial_settings import DialSettings
from quickapp.common.perf_timer.perf_timer import PerformanceTimer
from quickapp.config.application import ApplicationConfig
from quickapp.config.tools.base import AttachmentConfig
from quickapp.config.toolsets.mcp import MCPToolSet, MCPServerInfo, MCPProtocol
from quickapp.dial_core_services.attachment_service import AttachmentService
from quickapp.mcp_tooling import MCPToolingModule
from tests.unit_tests.common import create_test_app
from tests.unit_tests.common.common import create_app_configuration


class MCPToolTest(unittest.IsolatedAsyncioTestCase):

    @patch(
        "quickapp.mcp_tooling._mcp_tool_initializer._MCPConnectionManager.call_mcp_tool",
        new_callable=AsyncMock,
    )
    @patch(
        "quickapp.mcp_tooling._mcp_tool_initializer._MCPConnectionManager.get_tools_list",
        new_callable=AsyncMock,
    )
    async def test_mcp_tool(self, mock_get_tools_list, mock_call_mcp_tool):
        # Prepare tools metadata (no coroutines on the tool objects)
        tool_1 = SimpleNamespace(name="test_tool1", description="A test tool 1", inputSchema={})
        tool_2 = SimpleNamespace(name="test_tool2", description="A test tool 2", inputSchema={})
        tool_3 = SimpleNamespace(name="test_tool3", description="A test tool 3", inputSchema={})
        tool_4 = SimpleNamespace(name="test_tool4", description="A test tool 4", inputSchema={})

        mock_get_tools_list.return_value = [tool_1, tool_2, tool_3, tool_4]

        # Mock attachment service upload
        mock_stage = MagicMock(spec=Stage)
        mock_dial_attachment_service = MagicMock(spec=AttachmentService)
        mock_dial_attachment_service.upload_attachment_to_core = AsyncMock()

        async def mock_upload(attachment):
            attachment.url = "mocked_url"
            attachment.data = None
            attachment.title = "Attachment"
            return attachment

        mock_dial_attachment_service.upload_attachment_to_core.side_effect = mock_upload

        # Provide call_mcp_tool results based on tool name (simulate CallToolResult-like objects)
        async def _call_side_effect(tool_name, **kwargs):
            if tool_name == "test_tool1":
                # text-only content
                return SimpleNamespace(
                    content=[SimpleNamespace(type="text", text="test_result_1")], isError=False
                )
            if tool_name == "test_tool2":
                # image content
                return SimpleNamespace(
                    content=[
                        ImageContent(
                            mimeType="image/png",
                            data=base64.b64encode(b"test_image_data").decode("utf-8"),
                            type="image",
                        )
                    ],
                    isError=False,
                )
            if tool_name == "test_tool3":
                # embedded text resource
                tr = TextResourceContents(
                    mimeType="text/plain", text="test_text_content", uri=AnyUrl("https://test_uri")
                )
                return SimpleNamespace(
                    content=[EmbeddedResource(resource=tr, type="resource")], isError=False
                )
            if tool_name == "test_tool4":
                # embedded blob resource
                br = BlobResourceContents(
                    mimeType="application/octet-stream",
                    blob=base64.b64encode(b"test_blob_content").decode("utf-8"),
                    uri=AnyUrl("https://test_blob_uri"),
                )
                return SimpleNamespace(
                    content=[EmbeddedResource(resource=br, type="resource")], isError=False
                )
            return SimpleNamespace(content=[], isError=False)

        mock_call_mcp_tool.side_effect = _call_side_effect

        mcp_toolset = MCPToolSet(
            type="mcp",
            mcp_server_info=MCPServerInfo(
                url="https://test/mcp", authorization=None, protocol=MCPProtocol.streamable_http
            ),
            name="mcp-toolset",
            description="Set with MCP tools",
        )

        def configure(binder: Binder) -> None:
            binder.bind(Stage, to=mock_stage)
            binder.bind(DialSettings, DialSettings(url="https://core"))
            binder.bind(DIAL_API_KEY, SecretStr("some_api_key"))
            binder.bind(DIAL_BEARER, to=InstanceProvider(SecretStr("some_token")))
            binder.bind(AttachmentService, mock_dial_attachment_service)
            binder.bind(
                ApplicationConfig,
                to=create_app_configuration([mcp_toolset]),
            )
            binder.bind(PerformanceTimer, to=PerformanceTimer)
            binder.multibind(list[ToolArgumentTransformer], to=[])

        app = create_test_app([MCPToolingModule, configure])

        @app.get("/")
        async def get_method(injector: Injector = Injected(Injector)):
            initializers = injector.get(list[CompletionInitializer])
            self.assertEqual(len(initializers), 1)
            initializer = initializers[0]
            await initializer.initialize()

            mock_get_tools_list.assert_called_once()

            tools = injector.get(list[StagedBaseTool])
            self.assertEqual(len(tools), 4)

            # Use the public async entrypoint `arun(tool_call_id, ...)`
            tool_1_instance = next((t for t in tools if t.name == "test_tool1"), None)
            tool_1_result = await tool_1_instance.arun("call-1")
            self.assertEqual(
                tool_1_result,
                CompletionResult(
                    tool_call_id="call-1",
                    content='test_result_1',
                    content_type='text/markdown',
                    attachments=None,
                ),
            )

            tool_2_instance = next((t for t in tools if t.name == "test_tool2"), None)
            tool_2_result = await tool_2_instance.arun("call-2")
            self.assertEqual(
                tool_2_result,
                CompletionResult(
                    tool_call_id="call-2",
                    content="",
                    content_type='text/markdown',
                    attachments=[
                        Attachment(
                            type='image/png',
                            title="Attachment",
                            data=None,
                            url="mocked_url",
                            reference_type=None,
                            reference_url=None,
                        )
                    ],
                    propagate_to_choice=[
                        Attachment(
                            type='image/png',
                            title='Attachment',
                            data=None,
                            url='mocked_url',
                            reference_type=None,
                            reference_url=None,
                        )
                    ],
                ),
            )

            tool_3_instance = next((t for t in tools if t.name == "test_tool3"), None)
            tool_3_result = await tool_3_instance.arun("call-3")
            self.assertEqual(
                tool_3_result,
                CompletionResult(
                    tool_call_id="call-3",
                    content="",
                    content_type='text/markdown',
                    attachments=[
                        Attachment(
                            type='text/plain',
                            title="Attachment",
                            data=None,
                            url="mocked_url",
                            reference_type=None,
                            reference_url=None,
                        )
                    ],
                ),
            )

            tool_4_instance = next((t for t in tools if t.name == "test_tool4"), None)
            tool_4_result = await tool_4_instance.arun("call-4")
            self.assertEqual(
                tool_4_result,
                CompletionResult(
                    tool_call_id="call-4",
                    content="",
                    content_type='text/markdown',
                    attachments=[
                        Attachment(
                            type='application/octet-stream',
                            title="Attachment",
                            data=None,
                            url="mocked_url",
                            reference_type=None,
                            reference_url=None,
                        )
                    ],
                ),
            )

        client = TestClient(app)
        response = client.get("/")
        self.assertEqual(response.status_code, 200)

    @patch(
        "quickapp.mcp_tooling._mcp_tool_initializer._MCPConnectionManager.call_mcp_tool",
        new_callable=AsyncMock,
    )
    @patch(
        "quickapp.mcp_tooling._mcp_tool_initializer._MCPConnectionManager.get_tools_list",
        new_callable=AsyncMock,
    )
    async def test_mcp_tool_narrow_supported_types_skips_non_matching(
        self, mock_get_tools_list, mock_call_mcp_tool
    ):
        """Non-matching attachments are neither uploaded nor appended to the result."""
        tool_1 = SimpleNamespace(name="img_tool", description="Image tool", inputSchema={})
        mock_get_tools_list.return_value = [tool_1]

        mock_stage = MagicMock(spec=Stage)
        mock_dial_attachment_service = MagicMock(spec=AttachmentService)
        mock_dial_attachment_service.upload_attachment_to_core = AsyncMock()

        async def mock_upload(attachment):
            attachment.url = "mocked_url"
            attachment.data = None
            attachment.title = "Attachment"
            return attachment

        mock_dial_attachment_service.upload_attachment_to_core.side_effect = mock_upload

        # Tool returns both image and text attachments
        async def _call_side_effect(tool_name, **kwargs):
            tr = TextResourceContents(
                mimeType="text/plain", text="some_text", uri=AnyUrl("https://example")
            )
            return SimpleNamespace(
                content=[
                    ImageContent(
                        mimeType="image/png",
                        data=base64.b64encode(b"img").decode("utf-8"),
                        type="image",
                    ),
                    EmbeddedResource(resource=tr, type="resource"),
                ],
                isError=False,
            )

        mock_call_mcp_tool.side_effect = _call_side_effect

        # Only allow image/* — text/plain should be skipped entirely
        mcp_toolset = MCPToolSet(
            type="mcp",
            mcp_server_info=MCPServerInfo(
                url="https://test/mcp", authorization=None, protocol=MCPProtocol.streamable_http
            ),
            name="mcp-toolset",
            description="MCP toolset",
            attachment=AttachmentConfig(supported_types=["image/*"]),
        )

        def configure(binder: Binder) -> None:
            binder.bind(Stage, to=mock_stage)
            binder.bind(DialSettings, DialSettings(url="https://core"))
            binder.bind(DIAL_API_KEY, SecretStr("some_api_key"))
            binder.bind(DIAL_BEARER, to=InstanceProvider(SecretStr("some_token")))
            binder.bind(AttachmentService, mock_dial_attachment_service)
            binder.bind(
                ApplicationConfig,
                to=create_app_configuration([mcp_toolset]),
            )
            binder.bind(PerformanceTimer, to=PerformanceTimer)
            binder.multibind(list[ToolArgumentTransformer], to=[])

        app = create_test_app([MCPToolingModule, configure])

        @app.get("/")
        async def get_method(injector: Injector = Injected(Injector)):
            initializers = injector.get(list[CompletionInitializer])
            await initializers[0].initialize()

            tools = injector.get(list[StagedBaseTool])
            self.assertEqual(len(tools), 1)

            result = await tools[0].arun("call-1")

            # Only image should survive — text/plain is skipped by _should_upload
            self.assertIsNotNone(result.attachments)
            self.assertEqual(len(result.attachments), 1)
            self.assertEqual(result.attachments[0].type, "image/png")

            # Upload should only be called once (for the image)
            self.assertEqual(mock_dial_attachment_service.upload_attachment_to_core.call_count, 1)

        client = TestClient(app)
        response = client.get("/")
        self.assertEqual(response.status_code, 200)
