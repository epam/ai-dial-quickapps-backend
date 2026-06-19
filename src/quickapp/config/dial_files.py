from typing import Literal

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from quickapp.common.base_config import PreviewField

DialFilesToolName = Literal[
    "list",
    "read_lines",
    "search",
    "find",
    "write",
    "edit",
    "delete",
    "copy",
    "move",
]


class ToolCallResultOffloadSettings(BaseSettings):
    """Env-level defaults for tool-call-result offloading (a dial-files sub-feature)."""

    model_config = SettingsConfigDict(env_prefix="TOOL_CALL_RESULT_OFFLOAD__")

    enabled_by_default: bool = Field(default=True)
    size_threshold: int = Field(default=40_000)
    excluded_tools: set[str] = Field(default=set())


class ToolCallResultOffloadConfig(BaseModel):
    """Per-app config for offloading oversized tool-call responses to DIAL files.

    Toggled by the explicit `enabled` flag; `size_threshold` / `excluded_tools`
    are carried regardless so an app can disable offload without losing its
    overrides. Field defaults come from `ToolCallResultOffloadSettings` so env
    vars set the global baseline.
    """

    enabled: bool = Field(
        default_factory=lambda: ToolCallResultOffloadSettings().enabled_by_default,
        description=(
            "Whether to offload oversized tool-call responses to a file. "
            "Defaults to the TOOL_CALL_RESULT_OFFLOAD__ENABLED_BY_DEFAULT env var. "
            "Requires read_lines and search to be exposed via enabled_tools."
        ),
    )
    size_threshold: int = Field(
        default_factory=lambda: ToolCallResultOffloadSettings().size_threshold,
        gt=0,
        description=(
            "Byte threshold above which a tool-call response is offloaded to a file. "
            "Defaults to the TOOL_CALL_RESULT_OFFLOAD__SIZE_THRESHOLD env var."
        ),
    )
    excluded_tools: set[str] = Field(
        default_factory=lambda: ToolCallResultOffloadSettings().excluded_tools,
        description=(
            "Additional tool names exempt from offloading. "
            "Defaults to the TOOL_CALL_RESULT_OFFLOAD__EXCLUDED_TOOLS env var."
        ),
    )


class DialFilesConfig(BaseModel):
    enabled_tools: Literal["all"] | list[DialFilesToolName] = Field(
        default="all",
        description=(
            "Which file tools to expose. Use 'all' for every tool, "
            "or a list to restrict (e.g. ['read_lines', 'search'])."
        ),
    )
    agent_home_dir: str = Field(
        default="",
        description=(
            "Optional sub-directory inside the agent's appdata folder used as the "
            "root for relative paths. Empty (default) means the appdata root. "
            "Must be a relative path; absolute 'files/...' URLs, leading '/', "
            "and '..' segments are rejected. Example: 'workspace/'."
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
