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

TOOL_NAME_PREFIX = "internal_file_"

_PATH_IN_TITLE = ParameterDisplayConfig(
    stage=FormattedParameterConfig(show_value_in_stage_title=True)
)


LIST_FILES_TOOL_CONFIG = InternalTool(
    open_ai_tool=OpenAiToolConfig(
        function=OpenAiToolFunction(
            name=f"{TOOL_NAME_PREFIX}list",
            description=(
                "List entries (files and folders) under a folder in DIAL storage. "
                "Depth-bounded recursion."
            ),
            parameters=OpenAiToolFunctionParameters(
                type=JsonTypeEnum.object,
                properties={
                    "path": ConfigurableSchemaSimpleType(
                        type=JsonTypeEnum.string,
                        description=(
                            "Relative folder path under the agent's home dir "
                            "(e.g. 'reports/'), or absolute DIAL folder URL starting with "
                            "'files/' (e.g. 'files/{bucket}/uploads/'). Folder paths end with '/'."
                        ),
                        display=_PATH_IN_TITLE,
                    ),
                    "max_depth": ConfigurableSchemaSimpleType(
                        type=JsonTypeEnum.integer,
                        description=(
                            "Recursion depth. 1 = immediate children only. "
                            "Range: [1, 10]. Default: 1."
                        ),
                    ),
                },
                required=["path"],
            ),
        )
    ),
    display=ToolDisplayConfig(stage=ToolStageConfig(name="List files")),
)

READ_FILE_LINES_TOOL_CONFIG = InternalTool(
    open_ai_tool=OpenAiToolConfig(
        function=OpenAiToolFunction(
            name=f"{TOOL_NAME_PREFIX}read_lines",
            description=(
                "Read a range of lines from a file stored in DIAL. "
                "Use start_line and end_line (0-indexed, end exclusive) to retrieve a slice. "
                "Prefer small initial windows (around 20 lines); widen on subsequent calls "
                "only if more context is needed."
            ),
            parameters=OpenAiToolFunctionParameters(
                type=JsonTypeEnum.object,
                properties={
                    "path": ConfigurableSchemaSimpleType(
                        type=JsonTypeEnum.string,
                        description=(
                            "Relative path under the agent's home dir "
                            "(e.g. 'reports/summary.md'), or absolute DIAL file URL "
                            "starting with 'files/' (for shared or user-uploaded files)."
                        ),
                        display=_PATH_IN_TITLE,
                    ),
                    "start_line": ConfigurableSchemaSimpleType(
                        type=JsonTypeEnum.integer,
                        description="First line to include (0-indexed).",
                    ),
                    "end_line": ConfigurableSchemaSimpleType(
                        type=JsonTypeEnum.integer,
                        description=(
                            "First line to exclude (0-indexed, like a Python slice end). "
                            "Start with at most ~20 lines on the first call; widen later "
                            "if more context is needed."
                        ),
                    ),
                },
                required=["path", "start_line", "end_line"],
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
                    "path": ConfigurableSchemaSimpleType(
                        type=JsonTypeEnum.string,
                        description=(
                            "Relative path under the agent's home dir, or absolute "
                            "DIAL file URL starting with 'files/'."
                        ),
                        display=_PATH_IN_TITLE,
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
                required=["path", "pattern"],
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
                "Create or overwrite a UTF-8 text file under the agent's home dir. "
                "Relative path only (absolute files/... URLs are rejected). "
                "Nested paths allowed; '..' rejected. Default content_type is text/plain. "
                "overwrite=False fails on collision; overwrite=True replaces with ETag guard."
            ),
            parameters=OpenAiToolFunctionParameters(
                type=JsonTypeEnum.object,
                properties={
                    "path": ConfigurableSchemaSimpleType(
                        type=JsonTypeEnum.string,
                        description=(
                            "Relative path under the agent's home dir. Forward slashes "
                            "for nesting. Rejected: leading '/', '..' segments, '../' "
                            "substring, empty segments, absolute 'files/...' URLs."
                        ),
                        display=_PATH_IN_TITLE,
                    ),
                    "content": ConfigurableSchemaSimpleType(
                        type=JsonTypeEnum.string,
                        description="UTF-8 text content of the file.",
                    ),
                    "content_type": ConfigurableSchemaSimpleType(
                        type=JsonTypeEnum.string,
                        description=(
                            "MIME type. Default: text/plain. "
                            "Common: text/markdown, text/csv, application/json."
                        ),
                    ),
                    "overwrite": ConfigurableSchemaSimpleType(
                        type=JsonTypeEnum.boolean,
                        description="If true, replace an existing file. Default: false.",
                    ),
                },
                required=["path", "content"],
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
                    "path": ConfigurableSchemaSimpleType(
                        type=JsonTypeEnum.string,
                        description=(
                            "Relative path under the agent's home dir "
                            "(e.g. 'reports/summary.md'). Absolute files/... URLs are rejected."
                        ),
                        display=_PATH_IN_TITLE,
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
                required=["path", "old_string", "new_string"],
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
                    "path": ConfigurableSchemaSimpleType(
                        type=JsonTypeEnum.string,
                        description=(
                            "Relative path under the agent's home dir "
                            "(e.g. 'reports/old.md'). Absolute files/... URLs are rejected."
                        ),
                        display=_PATH_IN_TITLE,
                    ),
                },
                required=["path"],
            ),
        )
    ),
    display=ToolDisplayConfig(stage=ToolStageConfig(name="Delete file")),
)

COPY_FILE_TOOL_CONFIG = InternalTool(
    open_ai_tool=OpenAiToolConfig(
        function=OpenAiToolFunction(
            name=f"{TOOL_NAME_PREFIX}copy",
            description=(
                "Copy a file server-side in DIAL storage. Source can be relative "
                "(agent's home dir) or absolute files/... URL. Destination must be "
                "relative. No bytes downloaded."
            ),
            parameters=OpenAiToolFunctionParameters(
                type=JsonTypeEnum.object,
                properties={
                    "source": ConfigurableSchemaSimpleType(
                        type=JsonTypeEnum.string,
                        description=(
                            "Relative path under the agent's home dir, or absolute "
                            "DIAL file URL starting with 'files/'. The file to copy."
                        ),
                        display=_PATH_IN_TITLE,
                    ),
                    "destination": ConfigurableSchemaSimpleType(
                        type=JsonTypeEnum.string,
                        description=(
                            "Relative path under the agent's home dir. "
                            "Absolute files/... URLs are rejected."
                        ),
                    ),
                    "overwrite": ConfigurableSchemaSimpleType(
                        type=JsonTypeEnum.boolean,
                        description="If true, replace an existing destination. Default: false.",
                    ),
                },
                required=["source", "destination"],
            ),
        )
    ),
    display=ToolDisplayConfig(stage=ToolStageConfig(name="Copy file")),
)

MOVE_FILE_TOOL_CONFIG = InternalTool(
    open_ai_tool=OpenAiToolConfig(
        function=OpenAiToolFunction(
            name=f"{TOOL_NAME_PREFIX}move",
            description=(
                "Move (rename) a file within the agent's home dir in DIAL storage. "
                "Both source and destination must be relative paths. The original file "
                "is removed by DIAL Core."
            ),
            parameters=OpenAiToolFunctionParameters(
                type=JsonTypeEnum.object,
                properties={
                    "source": ConfigurableSchemaSimpleType(
                        type=JsonTypeEnum.string,
                        description=(
                            "Relative path under the agent's home dir. "
                            "Absolute files/... URLs are rejected."
                        ),
                        display=_PATH_IN_TITLE,
                    ),
                    "destination": ConfigurableSchemaSimpleType(
                        type=JsonTypeEnum.string,
                        description=(
                            "Relative path under the agent's home dir. "
                            "Absolute files/... URLs are rejected."
                        ),
                    ),
                    "overwrite": ConfigurableSchemaSimpleType(
                        type=JsonTypeEnum.boolean,
                        description="If true, replace an existing destination. Default: false.",
                    ),
                },
                required=["source", "destination"],
            ),
        )
    ),
    display=ToolDisplayConfig(stage=ToolStageConfig(name="Move file")),
)

ALL_FILE_TOOL_CONFIGS = [
    LIST_FILES_TOOL_CONFIG,
    READ_FILE_LINES_TOOL_CONFIG,
    SEARCH_IN_FILE_TOOL_CONFIG,
    WRITE_FILE_TOOL_CONFIG,
    EDIT_FILE_TOOL_CONFIG,
    DELETE_FILE_TOOL_CONFIG,
    COPY_FILE_TOOL_CONFIG,
    MOVE_FILE_TOOL_CONFIG,
]
