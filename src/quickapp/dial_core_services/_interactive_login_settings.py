from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class InteractiveLoginSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='dial_')

    interactive_login_timeout_seconds: float = Field(
        default=120.0,
        description="Wall-clock timeout in seconds for waiting on user sign-in via interactive login.",
    )
