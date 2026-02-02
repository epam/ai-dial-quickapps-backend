import json
from typing import Any, Optional

from httpx import URL, Headers, QueryParams
from injector import inject
from pydantic import BaseModel

from quickapp.common import DIAL_BEARER
from quickapp.common.media_types import MediaTypes
from quickapp.common.oauth_token_fetcher import OAuthTokenFetcher
from quickapp.config.tools.base import ConfigurableSchemaConst
from quickapp.config.tools.rest_api import ToolEndpointInfoMethodType, ToolEndpointParamType
from quickapp.config.toolsets.authorization import AuthorizationLocation, AuthorizationType
from quickapp.config.toolsets.rest_api import ApiKeyAuthorization, Authorization

from ._request_details import _RequestDetails


@inject
class _RequestDetailsBuilder:
    DEFAULT_HEADERS = {
        'Accept': ', '.join(
            [
                MediaTypes.JSON,
                MediaTypes.XML,
                MediaTypes.HTML,
                MediaTypes.CSV,
                MediaTypes.TEXT_JSON,
                MediaTypes.TEXT_XML,
                MediaTypes.TEXT_HTML,
                MediaTypes.TEXT_CSV,
                MediaTypes.MARKDOWN,
                MediaTypes.PLAIN_TEXT,
            ]
        )
        + '; charset=utf-8'
    }

    def __init__(self, oauth_token_fetcher: OAuthTokenFetcher, bearer: DIAL_BEARER = None):
        self.__oauth_token_fetcher: OAuthTokenFetcher = oauth_token_fetcher
        self.__bearer: DIAL_BEARER = bearer
        self.__headers: Headers = Headers(self.DEFAULT_HEADERS)
        self.__params: QueryParams = QueryParams()
        self.__data: dict[str, Any] = {}
        self.__url: Optional[URL] = None
        self.__method: Optional[str] = None

    @staticmethod
    def __process_value(value: Any) -> Any:
        if isinstance(value, (dict, list, BaseModel)):
            if isinstance(value, BaseModel):
                value = value.model_dump()
            return json.dumps(value)
        return value

    def __add_body_param(self, param_key: str, value: Any):
        if value is not None:
            self.__data[param_key] = self.__process_value(value)

    def __add_header_param(self, param_key: str, value: Any):
        if value is not None:
            self.__headers[param_key] = str(self.__process_value(value))

    def __add_query_param(self, param_key: str, value: Any):
        match value:
            case None:
                pass  # pass if the value is None
            case list():
                self.__params = self.__params.merge(
                    QueryParams({param_key: ",".join(map(str, value))})
                )
            case dict() | BaseModel():
                if isinstance(value, BaseModel):
                    value = value.model_dump()
                self.__params = self.__params.merge(QueryParams({param_key: json.dumps(value)}))
            case _:
                self.__params = self.__params.merge(QueryParams({param_key: value}))

    def __add_url_param(self, param_key: str, value: Any):
        if self.__url is None:
            raise ValueError("Url must be set before adding parameters")
        if isinstance(value, (str, bool, int, float)):
            path = self.__url.path.replace(f"{{{param_key}}}", str(value))
            self.__url = self.__url.copy_with(path=path)
        elif value is None:
            raise ValueError(f"Missing required URL parameter: {param_key}")
        else:
            raise TypeError(
                f"URL parameter '{param_key}' must be one of the types: str, bool, int, float. Got {type(value).__name__}"
            )

    def __handle_api_key_auth(self, auth_info: Authorization):
        if not isinstance(auth_info, ApiKeyAuthorization):
            raise TypeError("Expected ApiKeyAuthorization")
        match auth_info.location:
            case AuthorizationLocation.header:
                self.__headers[auth_info.name] = auth_info.key
            case AuthorizationLocation.query:
                self.__params = self.__params.merge(QueryParams({auth_info.name: auth_info.key}))
            case AuthorizationLocation.body:
                self.__data[auth_info.name] = auth_info.key

    def build(self):
        if self.__url is None:
            raise ValueError("URL must be set.")
        if self.__method is None:
            raise ValueError("HTTP method must be set.")
        return _RequestDetails(
            self.__url, self.__method, self.__headers, self.__params, self.__data
        )

    def with_url(self, url: str):
        self.__url = URL(url)
        return self

    def with_method(self, method: ToolEndpointInfoMethodType):
        self.__method = method.upper()
        return self

    async def with_auth(self, auth_info: Authorization):
        if auth_info is not None:
            match auth_info.type:
                case AuthorizationType.basic:
                    import base64

                    credentials = f"{auth_info.username}:{auth_info.password}"  # type: ignore[union-attr]
                    encoded_credentials = base64.b64encode(credentials.encode('utf-8')).decode(
                        'utf-8'
                    )
                    self.__headers['Authorization'] = f"Basic {encoded_credentials}"
                case AuthorizationType.bearer:
                    self.__headers['Authorization'] = f"Bearer {auth_info.token}"  # type: ignore[union-attr]
                case AuthorizationType.client_id_secret:
                    token = await self.__oauth_token_fetcher.fetch_oauth_token(auth_info)
                    self.__headers['Authorization'] = f"Bearer {token}"
                case AuthorizationType.api_key:  # type: ignore[union-attr]
                    self.__handle_api_key_auth(auth_info)
                case AuthorizationType.forward_auth_token:
                    if self.__bearer is None:
                        raise ValueError(
                            "Missing forwarded bearer token for AuthorizationType.forward_auth_token"
                        )
                    self.__headers['Authorization'] = f"Bearer {self.__bearer.get_secret_value()}"
        return self

    def with_parameters(self, parameters: dict[str, Any], **kwargs: Any):
        for param_name, param_info in parameters.items():
            value = (
                param_info.const
                if isinstance(param_info, ConfigurableSchemaConst)
                else kwargs.get(param_name)
            )

            match param_info.parameter_info.type:
                case ToolEndpointParamType.url:
                    self.__add_url_param(param_info.parameter_info.key, value)
                case ToolEndpointParamType.query:
                    self.__add_query_param(param_info.parameter_info.key, value)
                case ToolEndpointParamType.header:
                    self.__add_header_param(param_info.parameter_info.key, value)
                case ToolEndpointParamType.body:
                    self.__add_body_param(param_info.parameter_info.key, value)
        return self
