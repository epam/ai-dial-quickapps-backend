from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class MemorySettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="memory_")

    url: str = Field(description="The URL of the memory service")
