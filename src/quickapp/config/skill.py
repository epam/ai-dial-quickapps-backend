from collections.abc import Sequence
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from quickapp.common.base_config import DialResourceConfigField, preview_model


# A model docstring becomes the schema `description` DIAL Chat's editor shows,
# so the rationale for this type lives in a comment instead.
#
# `url` addresses the skill as a unit - never a file inside it, never a grouping
# folder. A malformed URL is rejected at *resolve* time rather than at
# config-parse time: a ValidationError here is not a ConfigResolutionException,
# so it would escape the one branch that renders the initialization-issues stage
# and fail the whole request over one trailing slash. The resolver turns it into
# a diagnostic and serves the rest.
@preview_model
class DialSkillConfig(BaseModel):
    """A skill stored in DIAL as a folder-shaped `skills/` resource."""

    type: Literal["dial-skill"] = Field(
        default="dial-skill",
        description="Skill sourced from a DIAL skill resource.",
    )
    url: Annotated[
        str,
        DialResourceConfigField(
            description="Relative skill resource URL in DIAL (e.g. skills/<bucket>/<path>)"
        ),
    ]


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
    DialSkillConfig | DialPromptSkillConfig,
    Field(discriminator="type"),
]


def enumerate_skill_configs[T: BaseModel](
    skill_configs: Sequence[SkillConfig] | None,
    config_type: type[T],
) -> list[tuple[int, T]]:
    """Select the entries of one skill type, keeping their position in ``skills``.

    Each initializer filters the configured list down to its own type, so
    without the index the original order is unrecoverable — and cross-source
    precedence is defined by exactly that order. Assigned here, before the
    split, so every source agrees on what "first configured" means.
    """
    return [
        (index, config)
        for index, config in enumerate(skill_configs or [])
        if isinstance(config, config_type)
    ]
