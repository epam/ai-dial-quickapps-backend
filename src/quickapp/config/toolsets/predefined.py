from typing import Literal

from pydantic import BaseModel, Field


class PredefinedToolSet(BaseModel):
    type: Literal["predefined"] = Field(
        default="predefined", description="The type of the tool set."
    )
    template_name: str = Field(description="Name of the predefined template")
