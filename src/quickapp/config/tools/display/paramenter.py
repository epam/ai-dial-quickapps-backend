from typing import Annotated, Callable, Literal

from pydantic import BaseModel, Field
from pydantic.json_schema import SkipJsonSchema


class CodeBlockFormatConfig(BaseModel):
    type: Literal["code_block"] = Field(
        default="code_block",
        description="The type of the markdown format. This is a code block format.",
    )
    code_type: str | None = Field(
        default=None,
        description="The type of the code block in markdown. Will be used in the template ```{code_type}```",
    )


class InlineCodeBlockFormatConfig(BaseModel):
    type: Literal["inline_code_block"] = Field(
        default="inline_code_block",
        description="The type of the markdown format. This is an inline code block format.",
    )


MarkdownParameterFormat = Annotated[
    CodeBlockFormatConfig,
    InlineCodeBlockFormatConfig,
    Field(discriminator="type"),
]


class FormattedParameterConfig(BaseModel):
    ignore: bool = Field(
        default=False,
        description="Whether to show parameter with value in the stage content.",
    )
    ignore_parameter_name: bool = Field(
        default=False,
        description="Whether to show parameter name in the stage content.",
    )
    show_value_in_stage_title: bool = Field(
        default=False,
        description="Whether to show parameter value in the stage title.",
    )
    name: str | None = Field(
        default=None,
        description="If present then will be used instead of original name, otherwise will be used original name.",
    )
    prefix: str | None = Field(
        default=None,
        description="The prefix to be added after parameter name and before parameter value.",
    )
    suffix: str | None = Field(
        default=None,
        description="The suffix to be added after parameter value.",
    )
    replaced_value_info: str | None = Field(
        default=None,
        description="The replaced parameter value that will shown in the stage content.",
    )
    format: str | None = Field(
        default=None,
        description="The format of the parameter value. If present then the value will be wrapped in ```{format} {parameter value}```.",
    )
    formatter: SkipJsonSchema[Callable[[str], str] | None] = Field(
        default=None,
        description="Runtime-only callable to transform the parameter value before display. Set programmatically; not serializable from JSON config.",
        exclude=True,
    )


class ParameterDisplayConfig(BaseModel):
    stage: FormattedParameterConfig | None = Field(
        default=None,
        description="The configuration for the parameter stage.",
    )
