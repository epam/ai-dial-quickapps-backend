from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from quickapp.common.base_config import DialResourceConfigField, LegacyAlias, LegacyAliasModel

# Mirrors `aidial_sdk.chat_completion.request.ReasoningEffort`, the DIAL contract for this
# field. A given deployment may advertise a narrower set in `features.reasoningEfforts`;
# values it does not support are rejected upstream rather than here.
ReasoningEffort = Literal["none", "minimal", "low", "medium", "high"]


class CustomFieldsConfig(BaseModel):
    configuration: dict[str, Any] | None = Field(
        default=None,
        description="The configuration for the custom fields.",
    )


# `StaticFunctionSpec` and `StaticFunctionTool` mirror `aidial_sdk.chat_completion.request`'s
# `StaticFunction` / `StaticTool` (which `ToolConfigCoreService.parse_static_tools_from_info` uses
# to read the same shape off DialCore metadata). They are mirrored rather than reused because the
# SDK models pick their pydantic version at import time from `PYDANTIC_V2`: without that env var
# they are v1 and `model_json_schema()` fails, which would make the published app schema depend on
# how the dumping process happens to be invoked. Local models also carry the editor-facing
# descriptions the SDK models have no reason to define. `extra="allow"` matches the SDK's
# `ExtraAllowModel`, so provider-specific keys still reach the deployment.
class StaticFunctionSpec(BaseModel):
    """The `static_function` payload of a static tool."""

    model_config = ConfigDict(extra="allow")

    name: str = Field(description="The name of the static function, e.g. `web_search`.")
    description: str | None = Field(
        default=None,
        description="The description of the static function.",
    )
    configuration: dict[str, Any] | None = Field(
        default=None,
        description="Provider-specific configuration for the static function.",
    )


class StaticFunctionTool(BaseModel):
    """A tool the target deployment executes on its own side, e.g. a web search."""

    model_config = ConfigDict(extra="allow")

    type: Literal["static_function"] = Field(default="static_function")
    static_function: StaticFunctionSpec = Field(
        description="The static function the deployment executes on its side."
    )


class DialDeploymentParameters(BaseModel):
    temperature: float | None = Field(
        default=None,
        description="The temperature for the model. A higher temperature means the model will take more risks.",
    )
    top_p: int | None = Field(
        default=None,
        description="The number of top tokens to sample from. A higher value means more randomness.",
    )
    seed: int | None = Field(
        default=None,
        description="The seed for the model. Can be used for enhancing reproducibility of models' responses.",
    )
    stop: str | list[str] | None = Field(
        default=None,
        description="Up to 4 sequences where the Assistant will stop generating further tokens.",
    )
    n: int | None = Field(
        default=None,
        description="How many chat completion choices to generate for each input message.",
    )
    max_tokens: int | None = Field(
        default=None,
        description="The maximum number of tokens to generate by the Assistant.",
    )
    presence_penalty: float | None = Field(
        default=None,
        description="A number between -2.0 and 2.0. Positive values impose a penalty on new tokens based on their appearance in the current text, thereby increasing the model's tendency to introduce new topics in its responses.",
    )
    frequency_penalty: float | None = Field(
        default=None,
        description="A number between -2.0 and 2.0. Positive values apply a penalty to new tokens according to their existing frequency in the preceding text, thereby reducing the model's propensity to repeat the exact same line.",
    )
    reasoning_effort: ReasoningEffort | None = Field(
        default=None,
        description="How much reasoning the model should spend before answering. "
        "Supported values differ per deployment (see its `features.reasoningEfforts`).",
    )
    custom_fields: CustomFieldsConfig | None = Field(
        default=None,
        description="The configuration parameters for the DIAL deployment. "
        "Schema is defined for specific deployment via configuration endpoint",
    )
    # ToDo: add more parameters according to the DIAL API reference


class DialDeploymentConfig(LegacyAliasModel):
    deployment_id: Annotated[
        str,
        DialResourceConfigField(description="The id of the DIAL deployment."),
        LegacyAlias("name"),
    ]
    parameters: DialDeploymentParameters = Field(
        default_factory=DialDeploymentParameters,
        description="The predefined parameters for the DIAL deployment.",
    )
    _configuration_param_names: set[str] = PrivateAttr(default_factory=set)


# `tools` lives here rather than on `DialDeploymentParameters` because the orchestrator builds
# its own `tools` payload from the configured tool set; a manifest-declared list would be
# overwritten there.
class DialDeploymentToolParameters(DialDeploymentParameters):
    """Parameters of the deployment a `deployment-tool` calls."""

    tools: list[StaticFunctionTool] | None = Field(
        default=None,
        description="Static tools the target deployment runs on its side, e.g. web search. "
        "They are forwarded to the deployment and never executed by the app.",
    )


class DialDeploymentToolConfig(DialDeploymentConfig):
    parameters: DialDeploymentToolParameters = Field(
        default_factory=DialDeploymentToolParameters,
        description="The predefined parameters for the DIAL deployment.",
    )
