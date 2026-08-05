import logging
from typing import Any, ClassVar

from aidial_sdk.chat_completion import Attachment
from injector import AssistedBuilder, inject
from mcp.types import BlobResourceContents, CallToolResult, TextResourceContents, Tool

from quickapp.common import StagedBaseTool, ToolCallResult
from quickapp.common.abstract.base_tool_argument_transformer import ToolArgumentTransformer
from quickapp.common.base_stage_wrapper import BaseStageWrapper
from quickapp.common.chat_completion_stream.argument_stream_presentation import ArgumentStreamMode
from quickapp.common.dial_settings import DialSettings
from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.common.payload_logging import log_payload
from quickapp.common.perf_timer.perf_timer import PerformanceTimer
from quickapp.common.state_holder import StateHolder
from quickapp.common.tool_timeout_utils import translate_timeout
from quickapp.common.url_classification import UrlScheme, classify_url
from quickapp.common.url_sanitization import sanitize_url_for_log
from quickapp.common.utils import generate_attachment_filename, matches_type
from quickapp.config.application import StageDisplayLevel
from quickapp.config.tools.mcp import MCPTool
from quickapp.dial_core_services._interactive_login_service import InteractiveLoginService
from quickapp.dial_core_services._login_result import LoginResult
from quickapp.dial_core_services.attachment_service import AttachmentService
from quickapp.dial_core_services.dial_file_service import DialFileService
from quickapp.mcp_tooling._mcp_stage_wrapper import _MCPStageWrapper
from quickapp.mcp_tooling._mcp_tool_error_exception import MCPToolErrorException
from quickapp.mcp_tooling._mcp_toolset_client import _MCPToolsetClient
from quickapp.mcp_tooling._mcp_unauthorized_exception import MCPUnauthorizedException
from quickapp.shared.config_resolvers.tool_timeout_resolver import ToolTimeoutResolver

logger = logging.getLogger(__name__)

_AUTH_CHALLENGE_META_KEY = "dial.epam.com/auth-challenge"
_EXTERNAL_SERVICE_SIGNIN_METHOD = "external-service/signin"


@inject
class _MCPTool(StagedBaseTool):
    argument_stream_mode: ClassVar[ArgumentStreamMode | None] = ArgumentStreamMode.JSON_OBJECT

    def __init__(
        self,
        tool: Tool,
        tool_config: MCPTool,
        toolset_client: _MCPToolsetClient,
        stage_wrapper_builder: AssistedBuilder[_MCPStageWrapper],
        state_holder: StateHolder,
        dial_attachment_service: AttachmentService,
        perf_timer: PerformanceTimer,
        file_service: DialFileService,  # todo combine DialFileService and AttachmentService.
        dial_toolset_id: str | None,
        login_service: InteractiveLoginService,
        timeout_resolver: ToolTimeoutResolver,
        dial_settings: DialSettings,
        stage_display_level: StageDisplayLevel = StageDisplayLevel.INFO,
        argument_transformers: list[ToolArgumentTransformer] | None = None,
    ):
        super().__init__(
            name=tool.name or "MCP Tool",
            tool_config=tool_config,
            description=tool.description or "MCP Tool",
            args_schema=tool.inputSchema,
            stage_wrapper_builder=stage_wrapper_builder,  # type: ignore[arg-type]
            perf_timer=perf_timer,
            stage_display_level=stage_display_level,
            argument_transformers=argument_transformers,
        )
        self.stage_name_component = f"Calling {tool.name} via MCP"
        self.__tool: Tool = tool
        self.__dial_attachment_service = dial_attachment_service
        self.__state_holder = state_holder
        self.__toolset_client: _MCPToolsetClient = toolset_client
        self.__file_service: DialFileService = file_service
        self.__dial_toolset_id = dial_toolset_id
        self.__login_service: InteractiveLoginService = login_service
        self.__timeout_resolver: ToolTimeoutResolver = timeout_resolver
        self.__dial_url: str = dial_settings.url

    async def _pre_process_params(self, **kwargs: Any) -> dict[str, Any]:
        kwargs = await super()._pre_process_params(**kwargs)

        # Grant permissions for dial_url-flagged parameters (MCP-specific)
        files_to_share = self._collect_dial_url_files(kwargs)
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

    def _collect_dial_url_files(self, kwargs: dict[str, Any]) -> list[str]:
        """Collect the values of ``dial_url``-flagged parameters as DIAL file paths.

        External or unsupported URLs are rejected with a parameter-aware
        ``InvalidToolCallParameterException`` — ``dial_url`` parameters require a
        DIAL file because permission-grant has no meaning for external resources.
        """
        properties = self.__tool.inputSchema.get("properties", {})
        files_to_share: list[str] = []
        for key, value in kwargs.items():
            if not properties.get(key, {}).get("dial_url"):
                continue
            candidates: list[str] = []
            if isinstance(value, str):
                candidates.append(value)
            elif isinstance(value, list):
                candidates.extend(elem for elem in value if isinstance(elem, str))
            for candidate in candidates:
                scheme = classify_url(candidate, self.__dial_url)
                if scheme == UrlScheme.EXTERNAL:
                    raise InvalidToolCallParameterException(
                        parameter_name=key,
                        message=(
                            f"Parameter `{key}` requires a DIAL file but received an "
                            "external URL. Use `file:data::` or `file:base64::` / "
                            "`file:text::` to "
                            "inline the content, or upload the file to DIAL first."
                        ),
                    )
                # TODO(#445): resolve appdir-relative paths via HomePathResolver
                #  instead of rejecting them.
                if scheme in (UrlScheme.UNSUPPORTED, UrlScheme.DIAL_APPDIR_RELATIVE):
                    raise InvalidToolCallParameterException(
                        parameter_name=key,
                        message=(
                            f"Parameter `{key}` requires a DIAL file but received an "
                            f"unsupported URL: {sanitize_url_for_log(candidate)}."
                        ),
                    )
            files_to_share.extend(candidates)
        return files_to_share

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

    @staticmethod
    def __extract_external_service_signin_scope(result: CallToolResult) -> str | None:
        """Extract the scope from an errored result's dial.epam.com/auth-challenge _meta entry."""
        if not getattr(result, "isError", False):
            return None
        meta = getattr(result, "meta", None)
        if not meta:
            return None
        challenges = meta.get(_AUTH_CHALLENGE_META_KEY)
        if not isinstance(challenges, list):
            return None
        for challenge in challenges:
            if (
                isinstance(challenge, dict)
                and challenge.get("method") == _EXTERNAL_SERVICE_SIGNIN_METHOD
            ):
                scope = challenge.get("scope")
                if isinstance(scope, str):
                    return scope
        return None

    async def __call_tool_with_signin(self, **kwargs: Any) -> CallToolResult:
        """Call the tool, recovering from either signin mechanism once, then return the result.

        A transport-level 401 (``MCPUnauthorizedException``) is only recoverable for a
        ``DialMCPToolSet`` (``toolset/signin``, keyed by ``dial_toolset_id``); an
        external-service signin challenge embedded in the result's ``_meta`` (`scope`) applies
        regardless of toolset type. On denied/timeout/error/no-channel for the latter, the
        original errored result is returned so the caller's ordinary ``isError`` handling
        raises ``MCPToolErrorException`` with the real error content.
        """
        try:
            result = await self.__toolset_client.call_mcp_tool(self.__tool.name, **kwargs)
        except MCPUnauthorizedException:
            if self.__dial_toolset_id is None:
                raise
            login_result = await self.__login_service.request_signin(self.__dial_toolset_id)
            if login_result != LoginResult.SUCCESS:
                raise
            return await self.__toolset_client.call_mcp_tool(self.__tool.name, **kwargs)

        scope = self.__extract_external_service_signin_scope(result)
        if scope is None:
            return result

        login_result = await self.__login_service.request_external_service_signin(scope)
        if login_result != LoginResult.SUCCESS:
            return result
        return await self.__toolset_client.call_mcp_tool(self.__tool.name, **kwargs)

    async def _run_in_stage_async(
        self,
        stage_wrapper: BaseStageWrapper | None,
        tool_call_id: str | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> ToolCallResult:
        logger.debug("MCP tool called with args: keys=%s", list(kwargs))
        log_payload(logger, "MCP tool called with args: %s", kwargs)

        timeout = self.__timeout_resolver.resolve()
        # Wrap the outer body: anyio task groups can raise BaseExceptionGroup, which
        # is not an Exception and would otherwise bypass `StagedBaseTool.arun()`.
        async with translate_timeout(self.__tool.name, timeout):
            tool_call_result = await self.__call_tool_with_signin(**kwargs)

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
                    logger.warning(
                        "Unsupported content block type: %s; treating as non-text", btype
                    )
                    non_text_contents.append(block)

            tool_content = "\n\n".join(filter(None, text_parts))

            # Detect-and-raise only; the StagedBaseTool choke point owns the failure
            # WARNING, so this stays at DEBUG (ownership rule). Structure only — the
            # response body and structuredContent are not logged (content rule, #436).
            if getattr(tool_call_result, "isError", False):
                logger.debug(
                    "MCP tool '%s' returned isError=True; content_length=%d, structured_content=%s",
                    self.__tool.name,
                    len(tool_content),
                    getattr(tool_call_result, "structuredContent", None) is not None,
                )
                raise MCPToolErrorException(self.__tool.name, tool_content)

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

            result = ToolCallResult(
                content=tool_content,
                content_type="text/markdown",
                attachments=attachments or None,
            )

            if stage_wrapper:
                stage_wrapper.add_result(result)

            return result
