from typing import Any

from pydantic import BaseModel, Field, PrivateAttr


class CustomFieldsConfig(BaseModel):
    configuration: dict[str, Any] | None = Field(
        default=None,
        description="The configuration for the custom fields.",
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
    custom_fields: CustomFieldsConfig | None = Field(
        default=None,
        description="The configuration parameters for the DIAL deployment. "
        "Schema is defined for specific deployment via configuration endpoint",
    )
    # ToDo: add more parameters according to the DIAL API reference


class DialDeploymentConfig(BaseModel):
    name: str = Field(description="The name of the DIAL deployment.")
    parameters: DialDeploymentParameters = Field(
        default_factory=DialDeploymentParameters,
        description="The predefined parameters for the DIAL deployment.",
    )
    _configuration_param_names: set[str] = PrivateAttr(default_factory=set)
