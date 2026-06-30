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
                "Add a file to the attachments of the current response. "
                "The file must be accessible via a URL (DIAL URL or external link). "
                "Use this to surface a file to the user in the final reply."
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
    # propagate_types_to_choice=[] disables StagedBaseTool's automatic type-based
    # auto-append from `attachments` to `propagate_to_choice`; the tool sets
    # `propagate_to_choice` directly. supported_types is left at its default so the
    # stage renders the attachment for any MIME type the agent supplies.
    attachment=AttachmentConfig(propagate_types_to_choice=[]),
)
