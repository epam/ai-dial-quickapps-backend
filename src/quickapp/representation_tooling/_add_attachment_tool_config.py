from quickapp.common.tool_names import INTERNAL_REPRESENTATION_ADD_ATTACHMENT_TOOL_NAME
from quickapp.config.tools.base import (
    AttachmentConfig,
    ConfigurableSchemaSimpleType,
    JsonTypeEnum,
    OpenAiToolConfig,
    OpenAiToolFunction,
    OpenAiToolFunctionParameters,
)
from quickapp.config.tools.display.tool import ToolDisplayConfig, ToolStageConfig
from quickapp.config.tools.internal import InternalTool

ADD_ATTACHMENT_TOOL_CONFIG = InternalTool(
    open_ai_tool=OpenAiToolConfig(
        function=OpenAiToolFunction(
            name=INTERNAL_REPRESENTATION_ADD_ATTACHMENT_TOOL_NAME,
            description=(
                "Attach a file to your final response so the user can open or download it. "
                "Call this whenever you produce or find a file the user should receive — a "
                "report you wrote (CSV, PDF, XLSX), a chart or image, a file returned by "
                "another tool, or a file attached earlier in the conversation. Call it "
                "separately for each file that should be visible to the user — a file stays "
                "hidden in the tool stage until this tool is called with its URL. The file must be "
                "reachable via a URL — a DIAL URL (e.g. files/bucket/path/report.csv) or an "
                "external link. After calling, do not restate the file name or say that you "
                "attached it — the file is shown to the user automatically."
            ),
            parameters=OpenAiToolFunctionParameters(
                type=JsonTypeEnum.object,
                properties={
                    "url": ConfigurableSchemaSimpleType(
                        type=JsonTypeEnum.string,
                        description="File URL — DIAL (e.g. files/bucket/path/report.csv) or external.",
                    ),
                    "title": ConfigurableSchemaSimpleType(
                        type=JsonTypeEnum.string,
                        description="Display name shown to the user. Optional.",
                    ),
                    "type": ConfigurableSchemaSimpleType(
                        type=JsonTypeEnum.string,
                        description="MIME type (e.g. text/csv, application/pdf). Default: text/plain.",
                    ),
                },
                required=["url"],
            ),
        )
    ),
    display=ToolDisplayConfig(stage=ToolStageConfig(name="Add attachment")),
    # propagate_types_to_choice=[]: the tool sets propagate_to_choice directly, so this
    # stops StagedBaseTool from auto-appending the same attachment a second time.
    attachment=AttachmentConfig(propagate_types_to_choice=[]),
)
