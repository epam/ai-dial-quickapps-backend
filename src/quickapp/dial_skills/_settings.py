from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class DialSkillsSettings(BaseSettings):
    """Operator-level limits for reading DIAL skill resources."""

    model_config = SettingsConfigDict()

    file_max_bytes: int = Field(
        default=262144,
        gt=0,
        description=(
            "Maximum size of a single file read from a DIAL skill, manifest included. "
            "Enforced after the response arrives: Core's file listing carries no size, "
            "so there is nothing to check beforehand. An over-cap SKILL.md drops the "
            "skill; an over-cap bundled file fails that read only."
        ),
        alias="DIAL_SKILLS_FILE_MAX_BYTES",
    )
    max_files: int = Field(
        default=200,
        gt=0,
        description=(
            "Maximum number of bundled files advertised per skill. Beyond it the "
            "inventory is truncated and says so."
        ),
        alias="DIAL_SKILLS_MAX_FILES",
    )
    listing_max_pages: int = Field(
        default=10,
        gt=0,
        description=(
            "Maximum number of pages followed when listing a skill's files. Bounds a "
            "server-supplied cursor so a stuck listing cannot hang initialization."
        ),
        alias="DIAL_SKILLS_LISTING_MAX_PAGES",
    )
