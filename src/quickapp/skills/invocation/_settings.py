from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class SkillInvocationSettings(BaseSettings):
    """Operator-level limits for skills the user invokes from a message."""

    model_config = SettingsConfigDict()

    max_skills: int = Field(
        default=10,
        gt=0,
        description=(
            "Maximum number of distinct picked skills resolved and listed per request "
            "across the conversation, newest first. Each one adds a <skill> block to the "
            "system prompt and one Core fetch on every turn."
        ),
        alias="SKILL_INVOCATION_MAX_SKILLS",
    )
