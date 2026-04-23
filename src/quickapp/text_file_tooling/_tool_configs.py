from quickapp.config.tools.base import (
    ConfigurableSchemaSimpleType,
    JsonTypeEnum,
    OpenAiToolConfig,
    OpenAiToolFunction,
    OpenAiToolFunctionParameters,
)
from quickapp.config.tools.display.paramenter import (
    FormattedParameterConfig,
    ParameterDisplayConfig,
)
from quickapp.config.tools.display.tool import ToolDisplayConfig, ToolStageConfig
from quickapp.config.tools.internal import InternalTool

_file_display_config = ParameterDisplayConfig(
    stage=FormattedParameterConfig(name="**File:** ", formatter=lambda value: value.split("/")[-1])
)

READ_FILE_LINES_TOOL_CONFIG = InternalTool(
    open_ai_tool=OpenAiToolConfig(
        function=OpenAiToolFunction(
            name="read_file_lines",
            description=(
                "Read a range of lines from a file stored in DIAL. "
                "Use start_line and end_line (0-indexed, end exclusive) to retrieve a slice."
            ),
            parameters=OpenAiToolFunctionParameters(
                type=JsonTypeEnum.object,
                properties={
                    "file_url": ConfigurableSchemaSimpleType(
                        type=JsonTypeEnum.string,
                        description="URL of the file to read.",
                        display=_file_display_config,
                    ),
                    "start_line": ConfigurableSchemaSimpleType(
                        type=JsonTypeEnum.integer,
                        description="First line to include (0-indexed).",
                    ),
                    "end_line": ConfigurableSchemaSimpleType(
                        type=JsonTypeEnum.integer,
                        description="First line to exclude (0-indexed). Like Python slice end.",
                    ),
                },
                required=["file_url", "start_line", "end_line"],
            ),
        )
    ),
    display=ToolDisplayConfig(stage=ToolStageConfig(name="Read file lines")),
)

READ_FILE_LINES_TOOL_NAME = READ_FILE_LINES_TOOL_CONFIG.open_ai_tool.function.name

SEARCH_IN_FILE_TOOL_CONFIG = InternalTool(
    open_ai_tool=OpenAiToolConfig(
        function=OpenAiToolFunction(
            name="search_in_file",
            description=(
                "Search for a substring in a file stored in DIAL. "
                "Returns matching lines with optional surrounding context."
            ),
            parameters=OpenAiToolFunctionParameters(
                type=JsonTypeEnum.object,
                properties={
                    "file_url": ConfigurableSchemaSimpleType(
                        type=JsonTypeEnum.string,
                        description="URL of the file to search.",
                        display=_file_display_config,
                    ),
                    "pattern": ConfigurableSchemaSimpleType(
                        type=JsonTypeEnum.string,
                        description="Substring to search for.",
                    ),
                    "context_lines": ConfigurableSchemaSimpleType(
                        type=JsonTypeEnum.integer,
                        description="Lines of context around each match. Default: 0.",
                    ),
                    "case_insensitive": ConfigurableSchemaSimpleType(
                        type=JsonTypeEnum.boolean,
                        description="If true, search is case-insensitive. Default: false.",
                    ),
                },
                required=["file_url", "pattern"],
            ),
        )
    ),
    display=ToolDisplayConfig(stage=ToolStageConfig(name="Search in file")),
)

SEARCH_IN_FILE_TOOL_NAME = SEARCH_IN_FILE_TOOL_CONFIG.open_ai_tool.function.name
