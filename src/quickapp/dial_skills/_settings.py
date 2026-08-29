from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class DialSkillsSettings(BaseSettings):
    """Bound on how much skill resolution one request may cost.

    The agent-facing caps live in ``SkillsSettings`` instead: they govern
    every source, while this one is specific to fetching configured DIAL skill
    resources.
    """

    model_config = SettingsConfigDict(env_prefix="dial_skills_")

    max_configured_skills: int = Field(
        default=20,
        gt=0,
        description=(
            "Maximum number of unique dial-skill URLs resolved per request. "
            "Counted after deduplication, so repeating one URL costs one slot."
        ),
    )
