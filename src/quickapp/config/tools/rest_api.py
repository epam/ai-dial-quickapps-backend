from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

from quickapp.config.tools.base import (
    BaseOpenAITool,
    ConfigurableSchemaArray,
    ConfigurableSchemaConst,
    ConfigurableSchemaObject,
    ConfigurableSchemaSimpleType,
)
from quickapp.config.tools.const import ALL_MIME_TYPES


class ToolEndpointParamType(str, Enum):
    query = 'query'
    url = 'url'
    body = 'body'
    header = 'header'


class RestApiEndpointHeaderParamInfo(BaseModel):
    type: ToolEndpointParamType
    key: str


class RestApiEndpointParamInfo(BaseModel):
    parameter_info: RestApiEndpointHeaderParamInfo


class RestApiEndpointSimpleTypeParam(ConfigurableSchemaSimpleType, RestApiEndpointParamInfo):
    pass


class RestApiEndpointConstParam(ConfigurableSchemaConst, RestApiEndpointParamInfo):
    pass


class RestApiEndpointObjectParam(ConfigurableSchemaObject, RestApiEndpointParamInfo):
    pass


class RestApiEndpointArrayParam(ConfigurableSchemaArray, RestApiEndpointParamInfo):
    pass


class ToolEndpointInfoMethodType(str, Enum):
    get = 'get'
    post = 'post'
    put = 'put'
    delete = 'delete'


class RestApiEndpointMethodInfo(BaseModel):
    method_url: str
    method_type: ToolEndpointInfoMethodType


class ResponseAsAttachmentConfig(BaseModel):
    enabled: bool = Field(
        default=False, description="Whether to wrap the HTTP response as an attachment."
    )
    content_types: list[str] = Field(
        default_factory=lambda: [ALL_MIME_TYPES],
        description="Which response Content-Types to convert to attachments.",
    )
    include_body_as_content: bool = Field(
        default=True,
        description="When an attachment is created, whether to also keep the response body as content.",
    )


class RestApiTool(
    BaseOpenAITool[
        RestApiEndpointObjectParam,
        RestApiEndpointArrayParam,
        RestApiEndpointSimpleTypeParam,
        RestApiEndpointConstParam,
    ]
):
    rest_api_method_info: RestApiEndpointMethodInfo
    type: Literal["restapi-tool"] = Field(default="restapi-tool")
    response_as_attachment: ResponseAsAttachmentConfig | None = Field(
        default=None,
        description="Configuration for converting HTTP responses into attachments.",
    )
