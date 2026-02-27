import logging
from typing import Any

from aidial_sdk.chat_completion import Attachment
from injector import AssistedBuilder, inject
from mcp.types import BlobResourceContents, TextResourceContents, Tool

from quickapp.common import CompletionResult, StagedBaseTool
from quickapp.common.abstract.base_tool_argument_transformer import ToolArgumentTransformer
from quickapp.common.base_stage_wrapper import BaseStageWrapper
from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.common.perf_timer.perf_timer import PerformanceTimer
from quickapp.common.state_holder import StateHolder
from quickapp.common.utils import generate_attachment_filename, matches_type
from quickapp.config.tools.mcp import MCPTool
from quickapp.dial_core_services.attachment_service import AttachmentService
from quickapp.dial_core_services.dial_file_service import DialFileService
from quickapp.mcp_tooling._mcp_connection_manager import _MCPConnectionManager
from quickapp.mcp_tooling._mcp_stage_wrapper import _MCPStageWrapper

logger = logging.getLogger(__name__)


@inject
class _MCPTool(StagedBaseTool):

    def __init__(
        self,
        tool: Tool,
        tool_config: MCPTool,
        connection_manager: _MCPConnectionManager,
        stage_wrapper_builder: AssistedBuilder[_MCPStageWrapper],
        state_holder: StateHolder,
        dial_attachment_service: AttachmentService,
        perf_timer: PerformanceTimer,
        file_service: DialFileService,  # todo combine DialFileService and AttachmentService.
        dial_toolset_id: str | None,
        argument_transformers: list[ToolArgumentTransformer] | None = None,
    ):
        super().__init__(
            name=tool.name or "MCP Tool",
            tool_config=tool_config,
            description=tool.description or "MCP Tool",
            args_schema=tool.inputSchema,
            stage_wrapper_builder=stage_wrapper_builder,  # type: ignore[arg-type]
            perf_timer=perf_timer,
            argument_transformers=argument_transformers,
        )
        self.stage_name_component = f"Calling {tool.name} via MCP"
        self.__tool: Tool = tool
        self.__dial_attachment_service = dial_attachment_service
        self.__state_holder = state_holder
        self.__connection_manager: _MCPConnectionManager = connection_manager
        self.__file_service: DialFileService = file_service
        self.__dial_toolset_id = dial_toolset_id

    async def _pre_process_params(self, **kwargs: Any) -> dict[str, Any]:
        kwargs = await super()._pre_process_params(**kwargs)

        # Grant permissions for dial_url-flagged parameters (MCP-specific)
        files_to_share: list[str] = []
        for key, value in kwargs.items():
            properties = self.__tool.inputSchema.get("properties", {})
            schema_prop = properties.get(key, {})
            if not schema_prop.get("dial_url"):
                continue
            if isinstance(value, str):
                files_to_share.append(value)
            elif isinstance(value, list):
                files_to_share.extend(elem for elem in value if isinstance(elem, str))

        if files_to_share:
            if not self.__dial_toolset_id:
                logger.error(
                    "Files with dial_url flag detected but dial_toolset_id is not set.",
                )
                raise InvalidToolCallParameterException(
                    parameter_name="file_url",
                    message="Files cannot be shared because dial_toolset_id is not configured.",
                )
            await self.__file_service.grant_permissions_to_files(
                files_to_share, self.__dial_toolset_id
            )

        return kwargs

    def _content_to_attachment(self, content: Any) -> Attachment | None:
        ctype = getattr(content, "type", None)

        if ctype == "image":
            title = generate_attachment_filename(
                getattr(content, "mimeType", None), base_filename=self.__tool.name
            )
            return Attachment(
                title=title,
                type=getattr(content, "mimeType", None),
                data=getattr(content, "data", None),
            )

        if ctype == "resource":
            resource = getattr(content, "resource", None)
            title = generate_attachment_filename(
                getattr(resource, "mimeType", None), base_filename=self.__tool.name
            )
            if isinstance(resource, TextResourceContents):
                return Attachment(
                    title=title,
                    type=getattr(resource, "mimeType", None),
                    data=getattr(resource, "text", None),
                )
            if isinstance(resource, BlobResourceContents):
                return Attachment(
                    title=title,
                    type=getattr(resource, "mimeType", None),
                    data=getattr(resource, "blob", None),
                )
            msg = f"Unsupported embedded resource type: {type(resource)}"
            logger.error(msg)
            raise NotImplementedError(msg)

        return None

    def _should_upload(self, mime_type: str | None) -> bool:
        return matches_type(mime_type, self._tool_config.attachment.supported_types)

    async def _run_in_stage_async(
        self, stage_wrapper: BaseStageWrapper | None, *args: Any, **kwargs: Any
    ) -> CompletionResult:

        logger.debug(f"MCP tool called with {kwargs}")

        tool_call_result = await self.__connection_manager.call_mcp_tool(self.__tool.name, **kwargs)
        # Handle error flag if present
        if getattr(tool_call_result, "isError", False):
            logger.error(
                "MCP tool call returned isError=True; structuredContent: %s",
                getattr(tool_call_result, "structuredContent", None),
            )

        contents = getattr(tool_call_result, "content", []) or []
        # Separate text blocks from non-text blocks
        text_parts: list[str] = []
        non_text_contents: list[Any] = []

        for block in contents:
            btype = getattr(block, "type", None)
            if btype == "text":
                text_parts.append(getattr(block, "text", "") or "")
            elif btype in ("image", "audio", "resource", "resource_link"):
                non_text_contents.append(block)
            else:
                logger.warning("Unsupported content block type: %s; treating as non-text", btype)
                non_text_contents.append(block)

        tool_content = "\n\n".join(filter(None, text_parts))

        logger.debug(
            "Tool returned text length %d and %d non-text content blocks",
            len(tool_content),
            len(non_text_contents),
        )

        attachments = []
        for content in non_text_contents:
            attachment = self._content_to_attachment(content)
            if attachment is not None and self._should_upload(attachment.type):
                attachment = await self.__dial_attachment_service.upload_attachment_to_core(
                    attachment
                )
                attachments.append(attachment)

        result = CompletionResult(
            content=tool_content,
            content_type="text/markdown",
            attachments=attachments or None,
        )

        if stage_wrapper:
            stage_wrapper.add_result(result)

        return result
