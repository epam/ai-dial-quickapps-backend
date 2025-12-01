from typing import Annotated, List, Literal, Union

from pydantic import Field

from quickapp.config.tools.predefined import PredefinedTool
from quickapp.config.tools.rest_api import RestApiTool
from quickapp.config.toolsets.authorization import (
    ApiKeyAuthorization,
    BasicAuthorization,
    BearerAuthorization,
    ClientIdSecretAuthorization,
)
from quickapp.config.toolsets.base import BaseToolSet

Authorization = Annotated[
    Union[
        BasicAuthorization, BearerAuthorization, ClientIdSecretAuthorization, ApiKeyAuthorization
    ],
    Field(discriminator="type"),
]


class RestApiToolSet(BaseToolSet):
    type: Literal["rest-api"] = Field(default="rest-api", description="The type of the tool set.")
    authorization: Authorization | None = None
    tools: List[RestApiTool | PredefinedTool] = Field(
        description="Tools with their configurations."
    )
