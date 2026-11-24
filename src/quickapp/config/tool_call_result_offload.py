from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from quickapp.config.tool_result_limit import ToolResultLimitSettings


class ToolCallResultOffloadSettings(BaseSettings):
    """Env-level defaults for tool-call-result offloading."""

    model_config = SettingsConfigDict(env_prefix="TOOL_CALL_RESULT_OFFLOAD__")

    enabled_by_default: bool = Field(default=True)
    size_threshold: int = Field(default=40_000)
    excluded_tools: set[str] = Field(default=set())

    @model_validator(mode="after")
    def _threshold_within_result_limit(self) -> "ToolCallResultOffloadSettings":
        # A response over the limit is rejected, so every size offload would take
        # (>= size_threshold bytes, hence >= size_threshold chars) must stay below it.
        max_chars = ToolResultLimitSettings().max_chars
        if self.size_threshold > max_chars:
            raise ValueError(
                f"TOOL_CALL_RESULT_OFFLOAD__SIZE_THRESHOLD ({self.size_threshold}) must not "
                f"exceed TOOL_CALL_RESULT_LIMIT__MAX_CHARS ({max_chars})"
            )
        return self


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
            "Requires read_lines and search to be exposed via dial_files.enabled_tools."
        ),
    )
    size_threshold: int = Field(
        default_factory=lambda: ToolCallResultOffloadSettings().size_threshold,
        gt=0,
        description=(
            "Byte threshold above which a tool-call response is offloaded to a file. "
            "Defaults to the TOOL_CALL_RESULT_OFFLOAD__SIZE_THRESHOLD env var. "
            "Must not exceed the TOOL_CALL_RESULT_LIMIT__MAX_CHARS env var."
        ),
    )
    excluded_tools: set[str] = Field(
        default_factory=lambda: ToolCallResultOffloadSettings().excluded_tools,
        description=(
            "Additional tool names exempt from offloading. "
            "Defaults to the TOOL_CALL_RESULT_OFFLOAD__EXCLUDED_TOOLS env var."
        ),
    )

    @field_validator("size_threshold")
    @classmethod
    def _validate_size_threshold(cls, value: int) -> int:
        max_chars = ToolResultLimitSettings().max_chars
        if value > max_chars:
            raise ValueError(
                f"size_threshold ({value}) must not exceed the maximum tool response length "
                f"({max_chars}, TOOL_CALL_RESULT_LIMIT__MAX_CHARS)"
            )
        return value
