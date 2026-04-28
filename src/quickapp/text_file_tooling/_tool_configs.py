from quickapp.config.tools.base import (
    ConfigurableSchemaSimpleType,
    JsonTypeEnum,
    OpenAiToolConfig,
    OpenAiToolFunction,
    OpenAiToolFunctionParameters,
)
from quickapp.config.tools.display.tool import ToolDisplayConfig, ToolStageConfig
from quickapp.config.tools.internal import InternalTool

TOOL_NAME_PREFIX = "internal_text_file_"

READ_FILE_LINES_TOOL_CONFIG = InternalTool(
    open_ai_tool=OpenAiToolConfig(
        function=OpenAiToolFunction(
            name=f"{TOOL_NAME_PREFIX}read_lines",
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

SEARCH_IN_FILE_TOOL_CONFIG = InternalTool(
    open_ai_tool=OpenAiToolConfig(
        function=OpenAiToolFunction(
            name=f"{TOOL_NAME_PREFIX}search",
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

WRITE_FILE_TOOL_CONFIG = InternalTool(
    open_ai_tool=OpenAiToolConfig(
        function=OpenAiToolFunction(
            name=f"{TOOL_NAME_PREFIX}write",
            description=(
                "Create a new UTF-8 text file in DIAL storage under generated-files/. "
                "Fails if a file with the same name already exists. Returns the file URL."
            ),
            parameters=OpenAiToolFunctionParameters(
                type=JsonTypeEnum.object,
                properties={
                    "filename": ConfigurableSchemaSimpleType(
                        type=JsonTypeEnum.string,
                        description="Simple file name (no path separators, no '..').",
                    ),
                    "content": ConfigurableSchemaSimpleType(
                        type=JsonTypeEnum.string,
                        description="UTF-8 text content of the file.",
                    ),
                },
                required=["filename", "content"],
            ),
        )
    ),
    display=ToolDisplayConfig(stage=ToolStageConfig(name="Write file")),
)

EDIT_FILE_TOOL_CONFIG = InternalTool(
    open_ai_tool=OpenAiToolConfig(
        function=OpenAiToolFunction(
            name=f"{TOOL_NAME_PREFIX}edit",
            description=(
                "Replace a unique substring in an existing UTF-8 text file. "
                "old_string must occur exactly once. Fails if the file changed concurrently."
            ),
            parameters=OpenAiToolFunctionParameters(
                type=JsonTypeEnum.object,
                properties={
                    "file_url": ConfigurableSchemaSimpleType(
                        type=JsonTypeEnum.string,
                        description="URL of the file to edit.",
                    ),
                    "old_string": ConfigurableSchemaSimpleType(
                        type=JsonTypeEnum.string,
                        description=(
                            "Exact substring to replace. Must occur exactly once. "
                            "Include surrounding context to disambiguate."
                        ),
                    ),
                    "new_string": ConfigurableSchemaSimpleType(
                        type=JsonTypeEnum.string,
                        description="Replacement text. May be empty to delete the match.",
                    ),
                },
                required=["file_url", "old_string", "new_string"],
            ),
        )
    ),
    display=ToolDisplayConfig(stage=ToolStageConfig(name="Edit file")),
)

DELETE_FILE_TOOL_CONFIG = InternalTool(
    open_ai_tool=OpenAiToolConfig(
        function=OpenAiToolFunction(
            name=f"{TOOL_NAME_PREFIX}delete",
            description="Delete a file from DIAL storage. Hard delete; no undo.",
            parameters=OpenAiToolFunctionParameters(
                type=JsonTypeEnum.object,
                properties={
                    "file_url": ConfigurableSchemaSimpleType(
                        type=JsonTypeEnum.string,
                        description="URL of the file to delete.",
                    ),
                },
                required=["file_url"],
            ),
        )
    ),
    display=ToolDisplayConfig(stage=ToolStageConfig(name="Delete file")),
)

ALL_FILE_TOOL_CONFIGS = [
    READ_FILE_LINES_TOOL_CONFIG,
    SEARCH_IN_FILE_TOOL_CONFIG,
    WRITE_FILE_TOOL_CONFIG,
    EDIT_FILE_TOOL_CONFIG,
    DELETE_FILE_TOOL_CONFIG,
]
