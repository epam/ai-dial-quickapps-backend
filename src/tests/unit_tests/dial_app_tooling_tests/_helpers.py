from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from pydantic import SecretStr

from quickapp.common.cache import CacheService
from quickapp.config.dial_deployment import DialDeploymentConfig
from quickapp.config.tools.base import (
    JsonTypeEnum,
    OpenAiToolConfig,
    OpenAiToolFunction,
    OpenAiToolFunctionParameters,
)
from quickapp.config.tools.deployment import DialDeploymentTool
from quickapp.config.toolsets.dial_app import DialAppToolSet
from quickapp.dial_app_tooling._dial_app_resolver import _DialAppResolver
from quickapp.dial_app_tooling._dial_app_resolver_context import _DialAppResolverContext
from tests.unit_tests.common.common import create_app_configuration


def make_metadata(*, mcp: bool | None = None, with_features: bool = True) -> SimpleNamespace:
    """Build a minimal Deployment-like object with a features namespace."""
    features = SimpleNamespace(mcp=mcp) if with_features else None
    return SimpleNamespace(id="deployment-id", features=features)


def make_tool_config(name: str = "deployment_id_tool") -> DialDeploymentTool:
    return DialDeploymentTool(
        deployment=DialDeploymentConfig(name="deployment-id"),
        open_ai_tool=OpenAiToolConfig(
            function=OpenAiToolFunction(
                name=name,
                description="Test tool",
                parameters=OpenAiToolFunctionParameters(type=JsonTypeEnum.object, properties={}),
            )
        ),
    )


def make_resolver(
    *,
    toolsets: list[DialAppToolSet],
    metadata: object | Exception = None,
    tool_config: DialDeploymentTool | None | Exception = None,
    api_key: str = "test-api-key",
    dial_url: str = "https://dial.example",
) -> tuple[_DialAppResolver, _DialAppResolverContext, MagicMock, MagicMock]:
    """Build a _DialAppResolver with all dependencies mocked.

    Returns (resolver, context, tool_config_service_mock, deployment_cache_mock).
    Set ``metadata`` to the object that ``get_deployment_metadata`` should return
    (or an Exception instance to raise); ``tool_config`` similarly controls what
    the cache's loader returns (or raises) on cache miss.
    """
    tool_config_service = MagicMock()
    if isinstance(metadata, Exception):
        tool_config_service.get_deployment_metadata = AsyncMock(side_effect=metadata)
    else:
        tool_config_service.get_deployment_metadata = AsyncMock(return_value=metadata)
    if isinstance(tool_config, Exception):
        tool_config_service.get_basic_tool_config = AsyncMock(side_effect=tool_config)
    else:
        tool_config_service.get_basic_tool_config = AsyncMock(return_value=tool_config)

    # Use a real CacheService so cache-sharing behaviour is exercised faithfully.
    deployment_cache = CacheService[DialDeploymentTool]()
    deployment_cache_spy = MagicMock(wraps=deployment_cache)
    deployment_cache_spy.get = AsyncMock(side_effect=deployment_cache.get)

    api_key_provider = MagicMock()
    api_key_provider.get.return_value = SecretStr(api_key)

    dial_settings = MagicMock(url=dial_url)

    app_config = create_app_configuration(toolsets)

    context = _DialAppResolverContext()

    resolver = _DialAppResolver(
        app_config=app_config,
        dial_settings=dial_settings,
        api_key_provider=api_key_provider,
        tool_config_service=tool_config_service,
        deployment_cache=deployment_cache_spy,
        context=context,
    )
    return resolver, context, tool_config_service, deployment_cache_spy
