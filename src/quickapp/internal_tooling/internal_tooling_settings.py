"""Internal tooling module settings. Env vars use aliases to match existing names."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class InternalToolingSettings(BaseSettings):
    """Settings for internal tools (content downloader, etc.)."""

    model_config = SettingsConfigDict(env_ignore_extra=True)

    content_downloader_file_size_limit: int = Field(
        default=20 * 1024 * 1024,  # 20 MiB
        description="Max file size for content downloader in bytes",
        alias="CONTENT_DOWNLOADER_FILE_SIZE_LIMIT",
    )
