from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ToolCallResultOffloadSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TOOL_CALL_RESULT_OFFLOAD__")

    enabled: bool = Field(default=True)
    size_threshold: int = Field(default=40_000)
    excluded_tools: set[str] = Field(default={"read_file_lines", "search_in_file"})
