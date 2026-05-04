from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class FileLoaderSettings(BaseSettings):
    """Settings for the agent's file loader. Loaded from env with aliases below."""

    model_config = SettingsConfigDict()

    size_limit: int = Field(
        default=10 * 1024 * 1024,
        description="Default maximum size (in bytes) for files the agent downloads",
        alias="DEFAULT_FILE_LOADER_SIZE_LIMIT",
        gt=0,
    )
