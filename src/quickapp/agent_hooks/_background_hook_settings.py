from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class BackgroundHookSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="background_hooks_")

    max_concurrent: int = Field(
        default=50,
        gt=0,
        description="Maximum number of background hooks running at once in this process. "
        "A hook that does not fit is rejected: it is logged at ERROR level and shown as a failed "
        "stage.",
    )
    warn_threshold: int = Field(
        default=40,
        ge=0,
        description="Number of running background hooks above which every newly started hook is "
        "logged with a warning. Must be below the maximum.",
    )
    response_hold_seconds: float = Field(
        default=3.0,
        ge=0,
        description="At most how long the response stays open after a turn so that background "
        "hooks' calls can reach DIAL Core (it exposes no 'call accepted' signal; a call arriving "
        "after the response closed gets a 401). Fast hooks end the wait early.",
    )
    shutdown_grace_seconds: float = Field(
        default=30.0,
        ge=0,
        description="How long shutdown waits for running background hooks before cancelling them.",
    )

    @model_validator(mode="after")
    def _threshold_below_maximum(self) -> "BackgroundHookSettings":
        if self.warn_threshold >= self.max_concurrent:
            raise ValueError(
                f"warn_threshold ({self.warn_threshold}) must be below "
                f"max_concurrent ({self.max_concurrent})"
            )
        return self
