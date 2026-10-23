"""Env-level limit on the size of a single tool response that may reach the model."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ToolResultLimitSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TOOL_CALL_RESULT_LIMIT__")

    max_chars: int = Field(
        default=80_000,
        gt=0,
        description=(
            "Maximum length, in characters, of a tool response passed to the model. A longer "
            "response (still over the limit after offload) is replaced by a 'response too "
            "large' error. Must be at least the offload size_threshold."
        ),
    )
