from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator

from quickapp.common.base_config import DialFileConfigField, preview_model

_FOLDER_MAX_DEPTH = 10


class FileContextConfig(BaseModel):
    type: Literal["file"] = Field(default="file", description="The type of the context.")
    url: Annotated[str, DialFileConfigField(description="Relative file URL in DIAL")]
    description: str | None = Field(
        default=None, description="The description of the file context."
    )


@preview_model
class FolderContextConfig(BaseModel):
    type: Literal["folder"] = Field(default="folder", description="The type of the context.")
    mime: str = Field(
        default="application/vnd.dial.metadata+json",
    )
    url: Annotated[str, DialFileConfigField(description="Relative file URL in DIAL")]
    description: str | None = Field(
        default=None, description="The description of the folder context."
    )
    max_depth: int = Field(
        default=_FOLDER_MAX_DEPTH,
        ge=1,
        le=_FOLDER_MAX_DEPTH,
        description=(
            "Maximum recursion depth when expanding folder contents into "
            "available-context entries (files and subfolders)."
        ),
    )

    @field_validator("url")
    @classmethod
    def _url_must_end_with_slash(cls, value: str) -> str:
        if not value.endswith("/"):
            raise ValueError("folder context url must end with '/'")
        return value


class UserDefinedContextConfig(BaseModel):
    type: Literal["user-defined"] = Field(
        default="user-defined", description="The type of the context."
    )
    content: str = Field(description="The content of the user-defined context.")


Context = Annotated[
    FileContextConfig | FolderContextConfig | UserDefinedContextConfig,
    Field(discriminator="type"),
]
