import logging

from fastapi_injector import request_scope
from injector import Binder, Module, ProviderOf, multiprovider, singleton

from quickapp.common import StagedBaseTool
from quickapp.common.base_initializer import CompletionInitializer
from quickapp.common.tool_initialization_exception import ToolInitializationException

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
    ) -> list[ToolInitializationException]:
        return context.exceptions
