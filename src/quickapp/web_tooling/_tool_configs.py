from quickapp.common.tool_names import INTERNAL_WEB_FETCH_TOOL_NAME
from quickapp.config.tools.base import (
    ConfigurableSchemaSimpleType,
    JsonTypeEnum,
    OpenAiToolConfig,
    OpenAiToolFunction,
    OpenAiToolFunctionParameters,
)
from quickapp.config.tools.display.tool import ToolDisplayConfig, ToolStageConfig
from quickapp.config.tools.internal import InternalTool
from quickapp.config.tools.tool_fallback import ContinueStrategyModel, ToolFallbackConfig

WEB_FETCH_TOOL_CONFIG = InternalTool(
    # Forward fetch-error messages (egress denied, non-text body, ...) so the model
    # sees the reason and can react, e.g. re-call with a save_path.
    fallback_configuration=ToolFallbackConfig(
        strategies=[ContinueStrategyModel(forward_tool_error_message=True)],
    ),
    open_ai_tool=OpenAiToolConfig(
        function=OpenAiToolFunction(
            name=INTERNAL_WEB_FETCH_TOOL_NAME,
            description=(
                "Fetch a resource from an external http(s) URL (e.g. a README, a "
                "source file, a documentation page). Without save_path it returns the "
                "text inline in a single call — text only: binary content (images, "
                "PDFs, archives) is rejected, re-call with a save_path instead. Text "
                "larger than the inline cap is returned truncated to its head with a "
                "notice stating the total size; the head is often enough, otherwise "
                "re-call with a save_path. With save_path it persists the resource "
                "(any content type) at that workspace-relative path under the agent "
                "home and returns the saved path (+ a short preview for text), so "
                "other available tools can process the full content. DIAL file paths "
                "(files/...) are not fetched here."
            ),
            parameters=OpenAiToolFunctionParameters(
                type=JsonTypeEnum.object,
                properties={
                    "url": ConfigurableSchemaSimpleType(
                        type=JsonTypeEnum.string,
                        description="The external http(s) URL to fetch.",
                    ),
                    "save_path": ConfigurableSchemaSimpleType(
                        type=JsonTypeEnum.string,
                        description=(
                            "Optional workspace-relative destination (e.g. 'data.py' or "
                            "'docs/readme.md'). Omit to read the content inline; provide "
                            "it to save the resource under the agent home and get back "
                            "the saved path. Must not be an absolute 'files/...' URL."
                        ),
                    ),
                },
                required=["url"],
            ),
        )
    ),
    display=ToolDisplayConfig(stage=ToolStageConfig(name="Fetch web page")),
)
