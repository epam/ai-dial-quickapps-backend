import logging
from typing import Any

from injector import AssistedBuilder, inject
from mcp.types import TextResourceContents

from quickapp.common import StagedBaseTool, ToolCallResult
from quickapp.common.abstract.base_tool_argument_transformer import ToolArgumentTransformer
from quickapp.common.base_stage_wrapper import BaseStageWrapper
from quickapp.common.perf_timer.perf_timer import PerformanceTimer
from quickapp.common.tool_names import INTERNAL_MCP_READ_RESOURCE_TOOL_NAME
from quickapp.config.application import StageDisplayLevel
from quickapp.config.tools.base import (
    ConfigurableSchemaSimpleType,
    JsonTypeEnum,
    OpenAiToolConfig,
    OpenAiToolFunction,
    OpenAiToolFunctionParameters,
)
from quickapp.config.tools.internal import InternalTool
from quickapp.mcp_tooling._mcp_stage_wrapper import _MCPStageWrapper
from quickapp.mcp_tooling._mcp_tooling_context import _MCPToolingContext
from quickapp.mcp_tooling._mcp_toolset_client import _MCPToolsetClient
from quickapp.mcp_tooling._mcp_unauthorized_exception import MCPUnauthorizedException

logger = logging.getLogger(__name__)

READ_MCP_RESOURCE_TOOL_CONFIG = InternalTool(
    enabled=True,
    open_ai_tool=OpenAiToolConfig(
        type="function",
        function=OpenAiToolFunction(
            name=INTERNAL_MCP_READ_RESOURCE_TOOL_NAME,
            description="Read the content of an MCP resource by its URI.",
            parameters=OpenAiToolFunctionParameters(
                type=JsonTypeEnum.object,
                properties={
                    "uri": ConfigurableSchemaSimpleType(
                        type=JsonTypeEnum.string,
                        description="URI of the resource to read.",
                    ),
                    "toolset": ConfigurableSchemaSimpleType(
                        type=JsonTypeEnum.string,
                        description=(
                            "Name of the toolset that owns the resource. "
                            "Required when multiple toolsets expose the same URI; "
                            "visible in the resource card header as "
                            "'--- Resource: ... ({toolset}) ---'."
                        ),
                    ),
                },
                required=["uri"],
            ),
        ),
    ),
)


@inject
class _ReadMcpResourceTool(StagedBaseTool):
    """Internal tool that reads MCP resource content by URI on demand."""

    def __init__(
        self,
        stage_wrapper_builder: AssistedBuilder[_MCPStageWrapper],
        tool_config: InternalTool,
        perf_timer: PerformanceTimer,
        context: _MCPToolingContext,
        stage_display_level: StageDisplayLevel = StageDisplayLevel.INFO,
        argument_transformers: list[ToolArgumentTransformer] | None = None,
        **kwargs: Any,
    ):
        super().__init__(
            stage_wrapper_builder=stage_wrapper_builder,  # type: ignore[arg-type]
            tool_config=tool_config,
            perf_timer=perf_timer,
            stage_display_level=stage_display_level,
            argument_transformers=argument_transformers,
            **kwargs,
        )
        self._context = context

    async def _run_in_stage_async(
        self,
        stage_wrapper: BaseStageWrapper | None = None,
        tool_call_id: str | None = None,
        uri: str | None = None,
        toolset: str | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> ToolCallResult:
        if not uri:
            result = ToolCallResult(
                content="Missing required parameter: uri", content_type="text/plain"
            )
            if stage_wrapper:
                stage_wrapper.add_result(result)
            return result

        # Find matching resource meta(s) by URI (+ optional toolset filter)
        candidates = [m for m in self._context.resource_metas if m.resource_uri == uri]
        if toolset:
            candidates = [m for m in candidates if m.toolset_name == toolset]

        if not candidates:
            msg = f"No resource registered with URI '{uri}'"
            result = ToolCallResult(content=msg, content_type="text/plain")
            if stage_wrapper:
                stage_wrapper.add_result(result)
            return result

        if len(candidates) > 1 and not toolset:
            names = ", ".join(m.toolset_name for m in candidates)
            msg = f"Multiple toolsets expose URI '{uri}': {names}. Specify the 'toolset' parameter."
            result = ToolCallResult(content=msg, content_type="text/plain")
            if stage_wrapper:
                stage_wrapper.add_result(result)
            return result

        meta = candidates[0]
        client: _MCPToolsetClient | None = self._context.clients.get(meta.toolset_name)
        if client is None:
            msg = f"No client registered for toolset '{meta.toolset_name}'"
            result = ToolCallResult(content=msg, content_type="text/plain")
            if stage_wrapper:
                stage_wrapper.add_result(result)
            return result

        try:
            contents = await client.read_mcp_resource(uri)
        except MCPUnauthorizedException:
            raise
        except Exception as e:
            logger.error("Failed to read resource '%s': %s", uri, e, exc_info=True)
            msg = f"Error reading resource '{uri}': {e}"
            result = ToolCallResult(content=msg, content_type="text/plain")
            if stage_wrapper:
                stage_wrapper.add_result(result)
            return result

        text_parts: list[str] = []
        for content in contents:
            if isinstance(content, TextResourceContents):
                text_parts.append(content.text or "")
            else:
                text_parts.append(
                    f"Resource '{uri}' contains binary content (blob). "
                    "Binary resources are not supported in this version."
                )

        text = "\n\n".join(filter(None, text_parts)) or f"Resource '{uri}' returned no content."
        result = ToolCallResult(content=text, content_type="text/plain")
        if stage_wrapper:
            stage_wrapper.add_result(result)
        return result
