import logging

from fastapi_injector import request_scope
from injector import AssistedBuilder, Binder, Module, multiprovider

from quickapp.common import StagedBaseTool
from quickapp.common.abstract.base_transformer import PreInvocationTransformer
from quickapp.common.abstract.completion_result_enricher import CompletionResultEnricher
from quickapp.common.time_provider import TimeProvider
from quickapp.config.application import ApplicationConfig
from quickapp.config.tools.predefined import PredefinedTool
from quickapp.config.toolsets.internal import InternalToolSet
from quickapp.timestamp_tooling._current_timestamp_tool import _CurrentTimestampTool
from quickapp.timestamp_tooling._timestamp_enrichment_transformer import (
    _TimestampEnrichmentTransformer,
)
from quickapp.timestamp_tooling._timestamp_metadata_enricher import _TimestampMetadataEnricher

logger = logging.getLogger(__name__)


class TimestampModule(Module):

    def configure(self, binder: Binder) -> None:
        binder.bind(_CurrentTimestampTool, to=_CurrentTimestampTool, scope=request_scope)

    @multiprovider
    def _provide_timestamp_tools(
        self,
        app_config: ApplicationConfig,
        ct_builder: AssistedBuilder[_CurrentTimestampTool],
    ) -> list[StagedBaseTool]:
        tools: list[StagedBaseTool] = []
        for tool_set in app_config.tool_sets:
            if isinstance(tool_set, InternalToolSet):
                for tool_config in tool_set.tools:
                    if not tool_config.enabled:
                        continue
                    if isinstance(tool_config, PredefinedTool):
                        logger.warning(
                            "Predefined tool wasn't substituted by real tool."
                            " Check application settings."
                        )
                    elif tool_config.open_ai_tool.function.name.startswith("current_timestamp"):
                        tools.append(
                            ct_builder.build(
                                tool_config=tool_config,
                                name=tool_config.open_ai_tool.function.name,
                                description=tool_config.open_ai_tool.function.description,
                            )
                        )
        return tools

    @multiprovider
    def _provide_enrichers(self, time_provider: TimeProvider) -> list[CompletionResultEnricher]:
        return [_TimestampMetadataEnricher(time_provider)]

    @multiprovider
    def _provide_pre_invocation_transformers(self) -> list[PreInvocationTransformer]:
        return [_TimestampEnrichmentTransformer()]
