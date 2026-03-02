import json
from enum import Enum
from hashlib import sha256
from typing import Annotated, Any, Generic, Literal, TypeVar, Union

from pydantic import BaseModel, Field, field_validator, model_validator

from quickapp.config.tools.const import ALL_MIME_TYPES
from quickapp.config.tools.display.paramenter import ParameterDisplayConfig
from quickapp.config.tools.display.tool import ToolDisplayConfig
from quickapp.config.tools.tool_fallback import ToolFallbackConfig


class JsonTypeEnum(str, Enum):
    object = 'object'
    array = 'array'
    string = 'string'
    number = 'number'
    integer = 'integer'
    boolean = 'boolean'
    null = 'null'
    const = 'const'


class ConfigurableParameter(BaseModel):
    display: ParameterDisplayConfig | None = Field(
        default=None,
        description="The configuration for the tool parameter in stage.",
    )
    default: Any | None = Field(default=None, description="The default value if value is not set")


class JsonSchemaConst(BaseModel):
    type: Literal[None]
    const: Any


class JsonSchemaSimpleType(BaseModel):
    type: Literal[
        JsonTypeEnum.string, JsonTypeEnum.number, JsonTypeEnum.integer, JsonTypeEnum.boolean
    ]
    description: str | None = None
    enum: list[Any] | None = None


class JsonSchemaObject(BaseModel):
    type: Literal[JsonTypeEnum.object]
    properties: dict[
        str,
        Annotated[
            Union[JsonSchemaSimpleType, JsonSchemaConst, 'JsonSchemaObject', 'JsonSchemaArray'],
            Field(discriminator='type'),
        ],
    ]
    description: str
    required: list[str] | None = None


class JsonSchemaArray(BaseModel):
    type: Literal[JsonTypeEnum.array]
    items: Annotated[
        Union[JsonSchemaSimpleType, JsonSchemaConst, JsonSchemaObject, 'JsonSchemaArray'],
        Field(discriminator='type'),
    ]
    description: str


JsonSchemaObject.model_rebuild()
JsonSchemaArray.model_rebuild()


class ConfigurableSchemaObject(JsonSchemaObject, ConfigurableParameter):
    pass


class ConfigurableSchemaArray(JsonSchemaArray, ConfigurableParameter):
    pass


class ConfigurableSchemaSimpleType(JsonSchemaSimpleType, ConfigurableParameter):
    pass


class ConfigurableSchemaConst(JsonSchemaConst, ConfigurableParameter):
    pass


TConfigurableJsonSchemaObject = TypeVar(
    'TConfigurableJsonSchemaObject', bound=ConfigurableSchemaObject
)
TConfigurableJsonSchemaArray = TypeVar(
    'TConfigurableJsonSchemaArray', bound=ConfigurableSchemaArray
)
TConfigurableSchemaSimpleType = TypeVar(
    'TConfigurableSchemaSimpleType', bound=ConfigurableSchemaSimpleType
)
TConfigurableSchemaConst = TypeVar('TConfigurableSchemaConst', bound=ConfigurableSchemaConst)


class OpenAiToolFunctionParameters(
    BaseModel,
    Generic[
        TConfigurableJsonSchemaObject,
        TConfigurableJsonSchemaArray,
        TConfigurableSchemaSimpleType,
        TConfigurableSchemaConst,
    ],
):
    type: Literal[JsonTypeEnum.object]
    properties: dict[
        str,
        Annotated[
            Union[
                TConfigurableJsonSchemaObject,
                TConfigurableJsonSchemaArray,
                TConfigurableSchemaSimpleType,
                TConfigurableSchemaConst,
            ],
            Field(discriminator='type'),
        ],
    ]
    required: list[str] | None = Field(default=None)


class OpenAiToolFunction(
    BaseModel,
    Generic[
        TConfigurableJsonSchemaObject,
        TConfigurableJsonSchemaArray,
        TConfigurableSchemaSimpleType,
        TConfigurableSchemaConst,
    ],
):
    parameters: OpenAiToolFunctionParameters[
        TConfigurableJsonSchemaObject,
        TConfigurableJsonSchemaArray,
        TConfigurableSchemaSimpleType,
        TConfigurableSchemaConst,
    ]
    description: str
    name: str

    # ToDo: move to before sending to LLM, and only if collision detected
    # Preventing name collisions for tools with same name but different parameters
    @model_validator(mode='after')
    def set_name(self):
        base = self.name.strip()
        # compute stable hash of the model excluding the name field
        payload = self.model_dump(exclude={'name'})
        json_str = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
        h = sha256(json_str.encode('utf-8')).hexdigest()[:4]
        suffix = f"_{h}"

        if base.endswith(suffix):
            # Already hashed — idempotent
            self.name = base
        else:
            # Truncate base if needed to ensure total length ≤ 64
            max_base_len = 64 - len(suffix)
            self.name = f"{base[:max_base_len]}{suffix}"
        return self


DEFAULT_PROPAGATE_TO_CHOICE = ["image/*", "application/vnd.plotly.v1+json"]


class AttachmentConfig(BaseModel):
    supported_types: list[str] | None = Field(
        default_factory=lambda: [ALL_MIME_TYPES],
        description="List of supported attachment types.",
    )
    propagate_types_to_choice: list[str] = Field(
        default_factory=lambda: DEFAULT_PROPAGATE_TO_CHOICE,
        description="List of attachment types to propagate from stage to choice.",
    )

    @field_validator("supported_types", mode="before")
    @classmethod
    def coerce_none_supported_types(cls, v: list[str] | None) -> list[str]:
        if v is None:
            return [ALL_MIME_TYPES]
        return v

    @field_validator("propagate_types_to_choice", mode="before")
    @classmethod
    def coerce_none_propagate_types(cls, v: list[str] | None) -> list[str]:
        if v is None:
            return DEFAULT_PROPAGATE_TO_CHOICE
        return v


class OpenAiToolConfig(
    BaseModel,
    Generic[
        TConfigurableJsonSchemaObject,
        TConfigurableJsonSchemaArray,
        TConfigurableSchemaSimpleType,
        TConfigurableSchemaConst,
    ],
):
    type: Literal['function'] = Field(default='function')
    function: OpenAiToolFunction[
        TConfigurableJsonSchemaObject,
        TConfigurableJsonSchemaArray,
        TConfigurableSchemaSimpleType,
        TConfigurableSchemaConst,
    ]


class BaseTool(BaseModel):
    attachment: AttachmentConfig = Field(
        default_factory=AttachmentConfig, description="Configuration for tool attachments."
    )
    fallback_configuration: ToolFallbackConfig = Field(
        default_factory=ToolFallbackConfig, description="Tool fallback configuration."
    )
    display: ToolDisplayConfig | None = Field(
        default=None, description="The configuration for the tool stage."
    )
    enabled: bool = Field(default=True, description="Whether the tool is enabled.")


class BaseOpenAITool(
    BaseTool,
    Generic[
        TConfigurableJsonSchemaObject,
        TConfigurableJsonSchemaArray,
        TConfigurableSchemaSimpleType,
        TConfigurableSchemaConst,
    ],
):
    open_ai_tool: OpenAiToolConfig[
        TConfigurableJsonSchemaObject,
        TConfigurableJsonSchemaArray,
        TConfigurableSchemaSimpleType,
        TConfigurableSchemaConst,
    ] = Field(description="JSON Schema with full tool configuration.")
