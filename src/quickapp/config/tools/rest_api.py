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
