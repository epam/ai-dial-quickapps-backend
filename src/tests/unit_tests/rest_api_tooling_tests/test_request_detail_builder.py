from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel

from quickapp.common.oauth_token_fetcher import OAuthTokenFetcher
from quickapp.config.tools.rest_api import (
    ConfigurableSchemaObject,
    ConfigurableSchemaSimpleType,
    RestApiEndpointArrayParam,
    RestApiEndpointConstParam,
    RestApiEndpointHeaderParamInfo,
    RestApiEndpointObjectParam,
    RestApiEndpointSimpleTypeParam,
    ToolEndpointParamType,
)
from quickapp.config.toolsets.authorization import (
    ApiKeyAuthorization,
    AuthorizationLocation,
    BasicAuthorization,
    BearerAuthorization,
    ClientIdSecretAuthorization,
)

# noinspection PyProtectedMember
from quickapp.rest_api_tooling._request_detail_builder import _RequestDetailsBuilder


@pytest.fixture
def builder():
    token_fetcher_mock = MagicMock(spec=OAuthTokenFetcher)
    token_fetcher_mock.fetch_oauth_token.return_value = "test_token"
    return _RequestDetailsBuilder(token_fetcher_mock)


def test_with_url(builder):
    builder.with_url("https://example.com").with_method("GET")
    result = builder.build()
    assert str(result.url) == "https://example.com"


def test_with_method(builder):
    builder.with_url("https://example.com").with_method("POST")
    result = builder.build()
    assert result.method == "POST"


@pytest.mark.asyncio
async def test_with_auth_basic(builder):
    builder.with_url("https://example.com").with_method("GET")
    auth_info = BasicAuthorization(
        username="user",
        password="test_password",
    )
    await builder.with_auth(auth_info)
    result = builder.build()
    assert result.headers["Authorization"] == "Basic dXNlcjp0ZXN0X3Bhc3N3b3Jk"


@pytest.mark.asyncio
async def test_with_auth_bearer(builder):
    builder.with_url("https://example.com").with_method("GET")
    auth_info = BearerAuthorization(
        token="test_token",
    )
    await builder.with_auth(auth_info)
    result = builder.build()
    assert result.headers["Authorization"] == "Bearer test_token"


@pytest.mark.asyncio
async def test_with_auth_client_id_secret(builder):
    builder.with_url("https://example.com").with_method("GET")
    auth_info = ClientIdSecretAuthorization(
        client_id="client_id",
        client_secret="client_secret",
        token_url="https://auth.example.com/token",
    )
    await builder.with_auth(auth_info)
    result = builder.build()
    assert result.headers["Authorization"] == "Bearer test_token"


@pytest.mark.asyncio
async def test_with_api_key(builder):
    builder.with_url("https://example.com").with_method("GET")
    auth_info = ApiKeyAuthorization(
        key="key",
        name="key_name",
        location=AuthorizationLocation.header,
    )
    await builder.with_auth(auth_info)
    result = builder.build()
    assert result.headers["key_name"] == "key"


@pytest.mark.asyncio
async def test_with_api_key_query(builder):
    builder.with_url("https://example.com").with_method("GET")
    auth_info = ApiKeyAuthorization(
        key="key",
        name="key_name",
        location=AuthorizationLocation.query,
    )
    await builder.with_auth(auth_info)
    result = builder.build()
    assert result.params["key_name"] == "key"


@pytest.mark.asyncio
async def test_with_api_key_body(builder):
    builder.with_url("https://example.com").with_method("POST")
    auth_info = ApiKeyAuthorization(
        key="key",
        name="key_name",
        location=AuthorizationLocation.body,
    )
    await builder.with_auth(auth_info)
    result = builder.build()
    assert result.data["key_name"] == "key"


def test_with_parameters(builder):
    builder.with_url("https://example.com/{key4}").with_method("GET")
    parameters = {
        "param1": RestApiEndpointSimpleTypeParam(
            parameter_info=RestApiEndpointHeaderParamInfo(
                type=ToolEndpointParamType.query, key="key1"
            ),
            type="string",
            description="Query parameter",
        ),
        "param2": RestApiEndpointSimpleTypeParam(
            parameter_info=RestApiEndpointHeaderParamInfo(
                type=ToolEndpointParamType.header, key="key2"
            ),
            type="string",
            description="Header parameter",
        ),
        "param3": RestApiEndpointSimpleTypeParam(
            parameter_info=RestApiEndpointHeaderParamInfo(
                type=ToolEndpointParamType.body, key="key3"
            ),
            type="string",
            description="Body parameter",
        ),
        "param4": RestApiEndpointSimpleTypeParam(
            parameter_info=RestApiEndpointHeaderParamInfo(
                type=ToolEndpointParamType.url, key="key4"
            ),
            type="string",
            description="URL parameter",
        ),
        "param5": RestApiEndpointConstParam(
            parameter_info=RestApiEndpointHeaderParamInfo(
                type=ToolEndpointParamType.query, key="key5"
            ),
            type=None,
            const="const_value",
        ),
        "param6": RestApiEndpointArrayParam(
            parameter_info=RestApiEndpointHeaderParamInfo(
                type=ToolEndpointParamType.query, key="key6"
            ),
            type="array",
            description="List parameter",
            items=ConfigurableSchemaSimpleType(type="string", description="List parameter"),
        ),
        "param7": RestApiEndpointObjectParam(
            parameter_info=RestApiEndpointHeaderParamInfo(
                type=ToolEndpointParamType.query, key="key7"
            ),
            type="object",
            description="Dictionary parameter",
            properties={
                "key8": ConfigurableSchemaObject(
                    type="object",
                    description="Object parameter",
                    properties={
                        "nested": ConfigurableSchemaSimpleType(
                            type="string", description="Nested object parameter"
                        )
                    },
                )
            },
        ),
        "param8": RestApiEndpointObjectParam(
            parameter_info=RestApiEndpointHeaderParamInfo(
                type=ToolEndpointParamType.query, key="key9"
            ),
            type="object",
            description="BaseModel parameter",
            properties={
                "key9": ConfigurableSchemaObject(
                    type="object",
                    description="Base model parameter",
                    properties={
                        "nested": ConfigurableSchemaSimpleType(
                            type="string", description="List parameter"
                        )
                    },
                )
            },
        ),
        "param9": RestApiEndpointObjectParam(
            parameter_info=RestApiEndpointHeaderParamInfo(
                type=ToolEndpointParamType.body, key="key10"
            ),
            type="object",
            description="BaseModel parameter",
            properties={
                "key10": ConfigurableSchemaObject(
                    type="object",
                    description="Base model parameter",
                    properties={
                        "nested": ConfigurableSchemaSimpleType(
                            type="string", description="Nested Object parameter"
                        )
                    },
                )
            },
        ),
        "param_none": RestApiEndpointSimpleTypeParam(
            parameter_info=RestApiEndpointHeaderParamInfo(
                type=ToolEndpointParamType.query, key="param_none"
            ),
            type="string",
            description="Body parameter",
        ),
    }

    class TestModel(BaseModel):
        field1: str
        field2: int

    model_instance = TestModel(field1="value1", field2=123)

    builder.with_parameters(
        parameters,
        param1="value1",
        param2="value2",
        param3="value3",
        param4="value4",
        param6=["item1", "item2"],
        param7={"key8": {"nested": "value"}},
        param8=model_instance,
        param9=model_instance,
        param_none=None,
    )
    result = builder.build()

    # Check query parameters
    assert result.params["key1"] == "value1"
    assert result.params["key5"] == "const_value"
    assert result.params["key6"] == "item1,item2"
    assert result.params["key7"] == '{"key8": {"nested": "value"}}'
    assert result.params["key9"] == '{"field1": "value1", "field2": 123}'
    assert "param_none" not in result.data
    # Check header parameters
    assert result.headers["key2"] == "value2"

    # Check body parameters
    assert result.data["key3"] == "value3"
    assert result.data["key10"] == '{"field1": "value1", "field2": 123}'

    # Check URL parameters
    assert str(result.url) == "https://example.com/value4"


def test_add_url_param_value_none(builder):
    builder.with_url("https://example.com/{key1}").with_method("GET")
    parameters = {
        "param1": RestApiEndpointSimpleTypeParam(
            parameter_info=RestApiEndpointHeaderParamInfo(
                type=ToolEndpointParamType.url, key="key1"
            ),
            type="string",
            description="URL parameter",
        ),
    }
    with pytest.raises(ValueError, match="Missing required URL parameter: key1"):
        builder.with_parameters(parameters, param1=None)


def test_add_url_param_unsupported_type(builder):
    builder.with_url("https://example.com/{key1}").with_method("GET")
    parameters = {
        "param1": RestApiEndpointSimpleTypeParam(
            parameter_info=RestApiEndpointHeaderParamInfo(
                type=ToolEndpointParamType.url, key="key1"
            ),
            type="string",
            description="URL parameter",
        ),
    }
    with pytest.raises(
        TypeError,
        match="URL parameter 'key1' must be one of the types: str, bool, int, float. Got list",
    ):
        builder.with_parameters(parameters, param1=["unsupported"])
