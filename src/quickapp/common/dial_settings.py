from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class DialSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='dial_')

    url: str = Field(description="The URL of the DIAL Core API")
    api_version: str = Field(
        "2025-01-01-preview", description="The API version to use for DIAL Core API"
    )
