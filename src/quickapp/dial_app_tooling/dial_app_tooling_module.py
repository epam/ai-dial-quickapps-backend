import logging

from fastapi_injector import request_scope
from injector import Binder, Module, ProviderOf, multiprovider

from quickapp.common.base_initializer import CompletionInitializer
from quickapp.common.exceptions import InitializationException
from quickapp.config.tools.deployment import DialDeploymentTool
from quickapp.config.toolsets.dial_mcp import DialMCPToolSet
from quickapp.config.toolsets.mcp import MCPToolSet

from ._dial_app_resolver import _DialAppResolver
from ._dial_app_resolver_context import _DialAppResolverContext

logger = logging.getLogger(__name__)


class DialAppToolingModule(Module):
    def configure(self, binder: Binder) -> None:
        binder.bind(_DialAppResolver, to=_DialAppResolver, scope=request_scope)
        binder.bind(_DialAppResolverContext, to=_DialAppResolverContext, scope=request_scope)
        logger.debug("DialAppToolingModule module configuration completed")

    @multiprovider
    def __provide_initializers(
        self, initializer_provider: ProviderOf[_DialAppResolver]
    ) -> list[CompletionInitializer]:
        return [initializer_provider.get()]

    @multiprovider
    def __provide_initialization_exceptions(
        self, context: _DialAppResolverContext
    ) -> list[InitializationException]:
        return context.exceptions

    @multiprovider
    def __provide_resolved_mcp_toolsets(
        self, context: _DialAppResolverContext
    ) -> list[MCPToolSet | DialMCPToolSet]:
        return list(context.resolved_mcp_toolsets)

    @multiprovider
    def __provide_resolved_deployment_tools(
        self, context: _DialAppResolverContext
    ) -> list[DialDeploymentTool]:
        return list(context.resolved_deployment_tools)
