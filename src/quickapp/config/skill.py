from typing import Annotated, Literal

from pydantic import BaseModel, Field

from quickapp.common.base_config import DialResourceConfigField


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


SkillConfig = Annotated[
    DialPromptSkillConfig,
    Field(discriminator="type"),
]
