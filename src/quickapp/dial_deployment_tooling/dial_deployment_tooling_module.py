import logging

from fastapi_injector import request_scope
from injector import Binder, Module, ProviderOf, multiprovider, provider, singleton
from openai.lib.azure import AsyncAzureOpenAI

from quickapp.common import DEPLOYMENT_AZURE_CLIENT, DIAL_API_KEY, ForwardedHeaders, StagedBaseTool
from quickapp.common.base_initializer import CompletionInitializer
from quickapp.common.dial_settings import DialSettings
from quickapp.common.exceptions import InitializationException
from quickapp.common.tool_timeout_resolver import ToolTimeoutResolver
from quickapp.common.tool_timeout_utils import build_async_dial_timeout

from ._deployment_tool_context import _DeploymentToolingContext
from ._deployment_tool_initializer import _DeploymentToolInitializer
from ._di_types import DialDeploymentToolCacheService
from .deployment_stage_wrapper import DeploymentStageWrapper
from .dial_completion_service import DialCompletionService

logger = logging.getLogger(__name__)


class DialDeploymentToolingModule(Module):

    def configure(self, binder: Binder) -> None:
        binder.bind(DialCompletionService, to=DialCompletionService, scope=request_scope)
        binder.bind(DeploymentStageWrapper, to=DeploymentStageWrapper)
        binder.bind(_DeploymentToolInitializer, to=_DeploymentToolInitializer)
        binder.bind(_DeploymentToolingContext, to=_DeploymentToolingContext, scope=request_scope)
        binder.bind(
            DialDeploymentToolCacheService, to=DialDeploymentToolCacheService, scope=singleton
        )
        logger.debug("DialDeploymentTooling module configuration completed")

    @provider
    def provide_deployment_openai_client(
        self,
        dial_settings: DialSettings,
        api_key: DIAL_API_KEY,
        forwarded_headers: ForwardedHeaders,
        timeout_resolver: ToolTimeoutResolver,
    ) -> DEPLOYMENT_AZURE_CLIENT:
        return AsyncAzureOpenAI(
            azure_endpoint=dial_settings.url,
            api_key=api_key.get_secret_value(),
            api_version=dial_settings.api_version,
            default_headers=forwarded_headers or None,
            timeout=build_async_dial_timeout(timeout_resolver.resolve()),
        )

    @multiprovider
    def __provide_tools(
        self,
        context: _DeploymentToolingContext,
    ) -> list[StagedBaseTool]:
        return context.tools

    @multiprovider
    def __provide_initializers(
        self, initializer_provider: ProviderOf[_DeploymentToolInitializer]
    ) -> list[CompletionInitializer]:
        return [initializer_provider.get()]

    @multiprovider
    def __provide_initialization_exceptions(
        self, context: _DeploymentToolingContext
    ) -> list[InitializationException]:
        return list(context.exceptions)
