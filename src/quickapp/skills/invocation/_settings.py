from pydantic import Field, model_validator
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

    max_skills_per_message: int = Field(
        default=5,
        gt=0,
        description=(
            "Maximum number of chips honoured on one message. The rest are dropped "
            "and reported when that message is the one being answered."
        ),
        alias="SKILL_INVOCATION_MAX_SKILLS_PER_MESSAGE",
    )

    @model_validator(mode="after")
    def _clamp_per_message_to_total(self) -> "SkillInvocationSettings":
        """A message can never usefully invoke more skills than the whole
        conversation is allowed to keep resolved, so clamp the per-message cap
        down to the total one instead of letting the two disagree."""
        if self.max_skills_per_message > self.max_skills:
            self.max_skills_per_message = self.max_skills
        return self
