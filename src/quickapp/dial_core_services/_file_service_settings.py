from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class FileServiceSettings(BaseSettings):
    """Settings for DialFileService. Loaded from env with aliases below."""

    model_config = SettingsConfigDict()

    max_download_size_bytes: int = Field(
        default=10 * 1024 * 1024,
        description="Default maximum size (in bytes) for files downloaded from DIAL Core",
        alias="DIAL_FILE_MAX_DOWNLOAD_BYTES",
        gt=0,
    )
