from typing import Annotated, Literal

from pydantic import BaseModel, Field


class VariablesConfig(BaseModel):
    variables: dict[str, str] = Field(description="The preset variable values")


class PredefinedSystemPromptConfig(BaseModel):
    type: Literal["predefined"] = Field(
        default="predefined", description="The type of the system prompt."
    )
    template: str = Field(
        description="The predefined template name for a system prompt", min_length=1
    )
    content: str | None = Field(description="The loaded prompt from template", default=None)


class CustomSystemPromptConfig(VariablesConfig):
    type: Literal["custom"] = Field(default="custom", description="The type of the system prompt.")
    content: str = Field(description="The content of the system prompt.")


class DialSystemPromptConfig(BaseModel):
    type: Literal["dial"] = Field(default="dial", description="The type of the system prompt.")
    path: str = Field(
        description="Relative path to the the system prompt in DIAL, including bucket"
    )
    variables: dict[str, str] | None = Field(
        default=None, description="Variables to be used in the DIAL system prompt"
    )
    content: str | None = Field(description="The loaded prompt from template", default=None)


AgentSystemPromptConfig = Annotated[
    CustomSystemPromptConfig | PredefinedSystemPromptConfig | DialSystemPromptConfig,
    Field(discriminator="type"),
]

ToolSystemPromptConfig = Annotated[
    CustomSystemPromptConfig | DialSystemPromptConfig,
    Field(discriminator="type"),
]
