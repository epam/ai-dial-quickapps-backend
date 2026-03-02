from typing import Annotated, List, Literal, Union

from pydantic import Field

from quickapp.config.tools.predefined import PredefinedTool
from quickapp.config.tools.rest_api import ResponseAsAttachmentConfig, RestApiTool
from quickapp.config.toolsets.authorization import (
    ApiKeyAuthorization,
    BasicAuthorization,
    BearerAuthorization,
    ClientIdSecretAuthorization,
    ForwardAuthTokenAuthorization,
)
from quickapp.config.toolsets.base import BaseToolSet

Authorization = Annotated[
    Union[
        BasicAuthorization,
        BearerAuthorization,
        ClientIdSecretAuthorization,
        ApiKeyAuthorization,
        ForwardAuthTokenAuthorization,
    ],
    Field(discriminator="type"),
]


class RestApiToolSet(BaseToolSet):
    type: Literal["rest-api"] = Field(default="rest-api", description="The type of the tool set.")
    authorization: Authorization | None = None
    response_as_attachment: ResponseAsAttachmentConfig | None = Field(
        default=None,
        description="Default response-as-attachment config for all tools in this toolset.",
    )
    tools: List[RestApiTool | PredefinedTool] = Field(
        description="Tools with their configurations."
    )
