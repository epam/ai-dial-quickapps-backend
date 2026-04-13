from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ToolTimeoutSettings(BaseSettings):
    """Deployment-wide default for tool-call timeouts.

    Always resolves to a positive float (default 300.0). Every tool client
    receives an explicit timeout at runtime — library defaults never apply.
    """

    model_config = SettingsConfigDict()

    default_tool_timeout_seconds: float = Field(
        default=300.0,
        gt=0,
        le=3600,
        description="Default timeout for tool calls, in seconds (0 < value <= 3600).",
        alias="DEFAULT_TOOL_TIMEOUT_SECONDS",
    )
