from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class SkillsSettings(BaseSettings):
    """Agent-facing caps on what a skill can put in front of the model.

    Source-neutral: they bound a predefined skill's bundled file exactly as
    they bound a DIAL skill's. Both sit *inside* DIAL Core's own per-resource
    ceilings — a skill Core stores happily can still exceed what QuickApps is
    willing to spend context on.
    """

    model_config = SettingsConfigDict(env_prefix="skills_")

    file_max_bytes: int = Field(
        default=40_000,
        gt=0,
        description=(
            "Maximum size of any skill file returned to the agent, SKILL.md "
            "included. Roughly 10k tokens — the largest single block that can "
            "enter a conversation without displacing the actual task."
        ),
    )
    inventory_max_entries: int = Field(
        default=200,
        gt=0,
        description=(
            "Bound on a skill's file inventory — both what is fetched from "
            "DIAL Core and what is rendered to the agent."
        ),
    )
