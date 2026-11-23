from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class BackgroundHookSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="background_hooks_")

    max_concurrent: int = Field(
        default=50,
        gt=0,
        description="Maximum number of background hooks running at once in this process. "
        "A hook that does not fit is skipped with a warning.",
    )
    shutdown_grace_seconds: float = Field(
        default=30.0,
        ge=0,
        description="How long shutdown waits for running background hooks before cancelling them.",
    )
