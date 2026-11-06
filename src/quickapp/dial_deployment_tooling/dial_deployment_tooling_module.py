import logging

from fastapi_injector import request_scope
from injector import Binder, Module, ProviderOf, multiprovider, singleton

from quickapp.common import StagedBaseTool
from quickapp.common.abstract.base_prompt_provider import PromptPartProvider
from quickapp.common.base_initializer import CompletionInitializer
from quickapp.common.deferred_tool_types import (
    DeferredToolCatalogEntry,
    DeferredToolDefinition,
    DeferredToolName,
    DeferredToolsetSummary,
)
from quickapp.common.deployment_tool_cache import DialDeploymentToolCacheService
from quickapp.common.exceptions import InitializationException
from quickapp.config.application import ApplicationConfig
from quickapp.config.toolsets.deployment import DeploymentToolSet
from quickapp.dial_deployment_tooling._annotation_anchor_prompt_provider import (
    _AnnotationAnchorPromptProvider,
)
from quickapp.dial_deployment_tooling._attachment_resolver import AttachmentResolver
from quickapp.dial_deployment_tooling._deployment_deferred_tools_context import (
    _DeploymentDeferredToolsContext,
)
from quickapp.dial_deployment_tooling._deployment_tool_context import _DeploymentToolingContext
from quickapp.dial_deployment_tooling._deployment_tool_initializer import _DeploymentToolInitializer
from quickapp.dial_deployment_tooling.deployment_stage_wrapper import DeploymentStageWrapper
from quickapp.dial_deployment_tooling.dial_completion_service import DialCompletionService

logger = logging.getLogger(__name__)


class DialDeploymentToolingModule(Module):

    def configure(self, binder: Binder) -> None:
        binder.bind(AttachmentResolver, to=AttachmentResolver, scope=request_scope)
        binder.bind(DialCompletionService, to=DialCompletionService, scope=request_scope)
        binder.bind(DeploymentStageWrapper, to=DeploymentStageWrapper)
        binder.bind(_DeploymentToolInitializer, to=_DeploymentToolInitializer)
        binder.bind(_DeploymentToolingContext, to=_DeploymentToolingContext, scope=request_scope)
        binder.bind(
            _DeploymentDeferredToolsContext,
            to=_DeploymentDeferredToolsContext,
            scope=request_scope,
        )
        binder.bind(
            _AnnotationAnchorPromptProvider, to=_AnnotationAnchorPromptProvider, scope=singleton
        )
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
    ) -> list[InitializationException]:
        return context.exceptions

    @multiprovider
    def _provide_deferred_tool_names(
        self, deferred_context: _DeploymentDeferredToolsContext
    ) -> list[DeferredToolName]:
        return list(deferred_context.deferred_names)

    @multiprovider
    def _provide_deferred_catalog_entries(
        self, deferred_context: _DeploymentDeferredToolsContext
    ) -> list[DeferredToolCatalogEntry]:
        return deferred_context.catalog

    @multiprovider
    def _provide_deferred_tool_definitions(
        self, deferred_context: _DeploymentDeferredToolsContext
    ) -> list[DeferredToolDefinition]:
        return [
            DeferredToolDefinition(name=name, definition=definition)
            for name in deferred_context.deferred_names
            if (definition := deferred_context.get_definition(name)) is not None
        ]

    @multiprovider
    def _provide_deferred_toolset_summaries(
        self, deferred_context: _DeploymentDeferredToolsContext
    ) -> list[DeferredToolsetSummary]:
        return deferred_context.toolset_summaries

    @staticmethod
    def _propagates_annotations(app_config: ApplicationConfig) -> bool:
        return any(
            bool(getattr(tool, "propagate_annotations_to_choice", None))
            for ts in (app_config.tool_sets or [])
            if isinstance(ts, DeploymentToolSet) and ts.enabled
            for tool in ts.tools
            if getattr(tool, "enabled", False)
        )

    @multiprovider
    def _provide_prompt_parts(
        self, app_config: ApplicationConfig, anchor_provider: _AnnotationAnchorPromptProvider
    ) -> list[PromptPartProvider]:
        if not self._propagates_annotations(app_config):
            return []
        return [anchor_provider]
