from typing import Literal, get_args

from pydantic import BaseModel, Field, field_validator

from quickapp.common.base_config import PreviewField
from quickapp.config.tool_call_result_offload import ToolCallResultOffloadConfig

DialFilesReadToolName = Literal["list", "read_lines", "read_chars", "search", "find"]
DialFilesWriteToolName = Literal["write", "edit", "delete", "copy", "move"]
DialFilesToolName = Literal[DialFilesReadToolName, DialFilesWriteToolName]

DialFilesToolPreset = Literal["all", "read_only"]

_READ_ONLY_TOOLS: frozenset[DialFilesToolName] = frozenset(get_args(DialFilesReadToolName))
_ALL_TOOLS: frozenset[DialFilesToolName] = frozenset(get_args(DialFilesToolName))


class DialFilesConfig(BaseModel):
    enabled_tools: DialFilesToolPreset | list[DialFilesToolName] = Field(
        default="all",
        description=(
            "Which file tools to expose. Use 'all' for every tool, 'read_only' for the "
            "non-mutating ones (list, read_lines, read_chars, search, find), or a list to "
            "restrict (e.g. ['read_lines', 'search']). When the whole `dial_files` block is "
            "omitted, 'all' applies."
        ),
    )
    agent_home_dir: str = Field(
        default="",
        description=(
            "Optional sub-directory inside the agent's appdata folder used as the "
            "root for relative paths. Empty (default) means the appdata root. "
            "Must be a relative path; absolute 'files/...' URLs, leading '/', "
            "and '..' segments are rejected. Example: 'workspace/'. Ignored in a project "
            "chat, where the home is the project's 'artifacts/' folder."
        ),
    )
    tool_call_result_offload: ToolCallResultOffloadConfig | None = PreviewField(  # type: ignore[assignment]
        default_factory=ToolCallResultOffloadConfig,
        description=(
            "Offload oversized tool-call responses to a file, read back on demand via the "
            "read_lines / search file tools. Toggled by its `enabled` flag, whose default is "
            "governed by TOOL_CALL_RESULT_OFFLOAD__ENABLED_BY_DEFAULT. "
            "Requires read_lines and search to be exposed via enabled_tools."
        ),
    )
    max_files_scanned: int = Field(
        default=50,
        ge=1,
        description=(
            "Folder-mode 'search' cap: the maximum number of files downloaded and "
            "scanned in a single call before the search stops and appends a truncation "
            "notice. Bounds worst-case egress on large subtrees."
        ),
    )

    @property
    def expanded_tools(self) -> frozenset[DialFilesToolName]:
        """`enabled_tools` (preset or explicit list) resolved to short tool names."""
        if self.enabled_tools == "all":
            return _ALL_TOOLS
        if self.enabled_tools == "read_only":
            return _READ_ONLY_TOOLS
        return frozenset(self.enabled_tools)

    @field_validator("agent_home_dir")
    @classmethod
    def _validate_agent_home_dir(cls, value: str) -> str:
        if value == "":
            return value
        if value.startswith("/"):
            raise ValueError("agent_home_dir must not start with '/'")
        if value.startswith("files/"):
            raise ValueError(
                "agent_home_dir must be a relative path under appdata, not an absolute 'files/' URL"
            )
        if not value.endswith("/"):
            raise ValueError("agent_home_dir must end with '/'")
        segments = value.split("/")
        if ".." in segments:
            raise ValueError("agent_home_dir must not contain '..' segments")
        if "" in segments[:-1]:
            raise ValueError("agent_home_dir must not contain empty segments")
        return value
