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

WEB_FETCH_TOOL_CONFIG = InternalTool(
    open_ai_tool=OpenAiToolConfig(
        function=OpenAiToolFunction(
            name=INTERNAL_WEB_FETCH_TOOL_NAME,
            description=(
                "Fetch a resource from an external http(s) URL (e.g. a README, a "
                "source file, a documentation page). Without save_path it returns the "
                "text inline in a single call — text only: binary content (images, "
                "PDFs, archives) or a resource too large to fit inline is rejected, "
                "re-call with a save_path instead. With save_path it persists the "
                "resource (any content type) at that workspace-relative path under the "
                "agent home and returns the saved path (+ a short preview for text), so "
                "you can then read it with internal_file_read_lines / "
                "internal_file_search. DIAL file paths (files/...) are not fetched "
                "here; read them with the file tools."
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
