from typing import Annotated, Literal

from pydantic import BaseModel, Field

from quickapp.common.base_config import DialFileConfigField


class FileContextConfig(BaseModel):
    type: Literal["file"] = Field(default="file", description="The type of the context.")
    url: Annotated[str, DialFileConfigField(description="Relative file URL in DIAL")]
    description: str | None = Field(
        default=None, description="The description of the file context."
    )


class UserDefinedContextConfig(BaseModel):
    type: Literal["user-defined"] = Field(
        default="user-defined", description="The type of the context."
    )
    content: str = Field(description="The content of the user-defined context.")


Context = Annotated[
    FileContextConfig | UserDefinedContextConfig,
    Field(discriminator="type"),
]
