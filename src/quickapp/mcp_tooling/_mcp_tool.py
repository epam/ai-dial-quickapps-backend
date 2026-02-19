import logging
from typing import Any

from aidial_sdk.chat_completion import Attachment
from injector import AssistedBuilder, inject
from mcp.types import BlobResourceContents, TextResourceContents, Tool

from quickapp.common import CompletionResult, StagedBaseTool
from quickapp.common.base_stage_wrapper import BaseStageWrapper
from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.common.perf_timer.perf_timer import PerformanceTimer
from quickapp.common.state_holder import StateHolder
from quickapp.common.utils import generate_attachment_filename, matches_type
from quickapp.config.tools.mcp import MCPTool
from quickapp.dial_core_services.attachment_service import AttachmentService
from quickapp.dial_core_services.file_downloader_service import DialFileService
from quickapp.mcp_tooling._file_prefix_handlers import FilePrefixHandlers
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
        file_service: DialFileService,
        dial_toolset_id: str | None,
    ):
        super().__init__(
            name=tool.name or "MCP Tool",
            tool_config=tool_config,
            description=tool.description or "MCP Tool",
            args_schema=tool.inputSchema,
            stage_wrapper_builder=stage_wrapper_builder,  # type: ignore[arg-type]
            perf_timer=perf_timer,
        )
        self.stage_name_component = f"Calling {tool.name} via MCP"
        self.__tool: Tool = tool
        self.__dial_attachment_service = dial_attachment_service
        self.__state_holder = state_holder
        self.__connection_manager: _MCPConnectionManager = connection_manager
        self.__file_service: DialFileService = file_service
        self.__dial_toolset_id = dial_toolset_id

    async def _pre_process_params(self, **kwargs: Any) -> Any:
        import re

        # todo for PoC only, will implement nested object handling later
        file_pattern = re.compile(
            r'^/*file:(?:(?P<prefix>base64|url|text)::)?(?P<file_url>.+)$', re.IGNORECASE
        )

        for key, value in list(kwargs.items()):
            if not isinstance(value, str):
                continue

            m = file_pattern.match(value)
            if not m:
                continue

            detected_prefix = m.group("prefix").lower() if m.group("prefix") else None
            file_url_part = m.group("file_url")

            files_to_share = []
            if detected_prefix == "base64":
                logger.debug(
                    "Detected 'base64' prefix for key %s (url: %s) - placeholder handling",
                    key,
                    file_url_part,
                )
                kwargs[key] = await FilePrefixHandlers.handle_base64(
                    file_url_part, self.__file_service
                )
            elif detected_prefix == "url":
                logger.debug(
                    "Detected 'url' prefix for key %s (url: %s) - placeholder handling",
                    key,
                    file_url_part,
                )
                properties = self.__tool.inputSchema.get("properties", {})
                schema_prop = properties.get(key, {})
                if schema_prop.get("dial_url"):
                    files_to_share.append(file_url_part)
                else:
                    kwargs[key] = file_url_part
            elif detected_prefix == "text":
                logger.debug(
                    "Detected 'text' prefix for key %s (text: %s) - placeholder handling",
                    key,
                    file_url_part,
                )
                kwargs[key] = await FilePrefixHandlers.handle_text(
                    file_url_part, self.__file_service, parameter_name=key
                )
            else:
                logger.warning(
                    "Detected file reference without prefix for key %s (value: %s)", key, value
                )
                raise InvalidToolCallParameterException(
                    parameter_name=key,
                    message="Missing required file prefix (base64::, url::, text::)",
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
            logger.exception(msg)
            raise NotImplementedError(msg)

        return None

    async def _maybe_upload_attachment(self, attachment: Attachment) -> Attachment:
        if self._tool_config and matches_type(
            attachment.type, self._tool_config.attachment.supported_types  # type: ignore[arg-type]
        ):
            logger.debug(f"Attachment: {attachment.title}, Tool Config: {self._tool_config}")
            return await self.__dial_attachment_service.upload_attachment_to_core(attachment)
        return attachment

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

        tool_content = "\n\n".join([p for p in text_parts if p]) or ""

        logger.debug(
            "Tool returned text length %d and %d non-text content blocks",
            len(tool_content),
            len(non_text_contents),
        )

        attachments = []
        for content in non_text_contents:
            attachment = self._content_to_attachment(content)
            if attachment is not None:
                attachment = await self._maybe_upload_attachment(attachment)
                attachments.append(attachment)

        result = CompletionResult(
            content=tool_content,
            content_type="text/markdown",
            attachments=attachments or None,
        )

        if stage_wrapper:
            stage_wrapper.add_result(result)

        return result
