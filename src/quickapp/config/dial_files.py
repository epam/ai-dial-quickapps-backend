from typing import Literal

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DialFilesToolName = Literal[
    "list",
    "read_lines",
    "search",
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
    excluded_tools: set[str] = Field(default={"internal_file_read_lines", "internal_file_search"})


class ToolCallResultOffloadConfig(BaseModel):
    """Per-app config for offloading oversized tool-call responses to DIAL files.

    Enabled by presence (mirrors how `features.dial_files` itself is enabled):
    an instance means on; `null` in the manifest means off. Field defaults come
    from `ToolCallResultOffloadSettings` so env vars set the global baseline.
    """

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
            "Tool names exempt from offloading (e.g. the read-back tools). "
            "Defaults to the TOOL_CALL_RESULT_OFFLOAD__EXCLUDED_TOOLS env var."
        ),
    )


def _default_tool_call_result_offload() -> ToolCallResultOffloadConfig | None:
    return (
        ToolCallResultOffloadConfig()
        if ToolCallResultOffloadSettings().enabled_by_default
        else None
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
    tool_call_result_offload: ToolCallResultOffloadConfig | None = Field(
        default_factory=_default_tool_call_result_offload,
        description=(
            "Offload oversized tool-call responses to a file, read back on demand via the "
            "read_lines / search file tools. Present (an object) enables it; null disables it. "
            "When omitted, the default is governed by TOOL_CALL_RESULT_OFFLOAD__ENABLED_BY_DEFAULT. "
            "Requires read_lines and search to be exposed via enabled_tools."
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
