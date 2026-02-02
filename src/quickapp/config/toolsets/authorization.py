from enum import Enum

from pydantic import BaseModel, Field


class AuthorizationType(str, Enum):
    basic = 'basic'
    bearer = 'bearer'
    client_id_secret = 'client_id_secret'
    api_key = 'api_key'
    forward_auth_token = 'forward_auth_token'


class AuthorizationLocation(str, Enum):
    header = 'header'
    query = 'query'
    body = 'body'


class BaseAuthorization(BaseModel):
    type: AuthorizationType = Field(description="Type of authorization")


from typing import Literal, Optional

from pydantic import Field


class BasicAuthorization(BaseAuthorization):
    type: Literal[AuthorizationType.basic] = Field(default=AuthorizationType.basic)
    username: str
    password: str


class BearerAuthorization(BaseAuthorization):
    type: Literal[AuthorizationType.bearer] = Field(default=AuthorizationType.bearer)
    token: str


class ForwardAuthTokenAuthorization(BaseAuthorization):
    type: Literal[AuthorizationType.forward_auth_token] = Field(
        default=AuthorizationType.forward_auth_token
    )


class ClientIdSecretAuthorization(BaseAuthorization):
    type: Literal[AuthorizationType.client_id_secret] = Field(
        default=AuthorizationType.client_id_secret
    )
    client_id: str
    client_secret: str
    token_url: str
    scope: Optional[str] = None
    aud: Optional[str] = None


class ApiKeyAuthorization(BaseAuthorization):
    type: Literal[AuthorizationType.api_key] = Field(default=AuthorizationType.api_key)
    key: str
    name: str
    location: AuthorizationLocation


class MCPApiKeyAuthorization(BaseAuthorization):
    type: Literal[AuthorizationType.api_key] = Field(default=AuthorizationType.api_key)
    key: str
    name: str
