from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ProjectSettings(BaseSettings):
    """Operator-level limits for project chats."""

    model_config = SettingsConfigDict()

    instructions_max_chars: int = Field(
        default=32_000,
        gt=0,
        description=(
            "Maximum length, in characters, of the PROJECT.md body added to the system "
            "prompt. A longer body is cut, with a note saying so."
        ),
        alias="PROJECT_INSTRUCTIONS_MAX_CHARS",
    )
