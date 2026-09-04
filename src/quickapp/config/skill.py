from typing import Annotated, Literal

from pydantic import BaseModel, Field

from quickapp.common.base_config import DialResourceConfigField, preview_model


class DialPromptSkillConfig(BaseModel):
    type: Literal["dial-prompt"] = Field(
        default="dial-prompt",
        description="Skill sourced from a DIAL prompt.",
    )
    url: Annotated[
        str,
        DialResourceConfigField(
            description="Relative prompt URL in DIAL (e.g. prompts/<bucket>/<path>)"
        ),
    ]


@preview_model
class DialSkillConfig(BaseModel):
    type: Literal["dial-skill"] = Field(
        default="dial-skill",
        description="Skill sourced from a DIAL skill resource (folder with SKILL.md).",
    )
    url: Annotated[
        str,
        DialResourceConfigField(
            description="Relative skill resource URL in DIAL (e.g. skills/<bucket>/<path>)"
        ),
    ]


SkillConfig = Annotated[
    DialPromptSkillConfig | DialSkillConfig,
    Field(discriminator="type"),
]
