import logging

from fastapi_injector import request_scope
from injector import AssistedBuilder, Binder, Module, ProviderOf, multiprovider, provider

from quickapp.common import TIMEZONE_HEADER_VALUE, StagedBaseTool
from quickapp.common.abstract.base_transformer import MessagesTransformer, PreInvocationTransformer
from quickapp.common.abstract.tool_call_result_enricher import ToolCallResultEnricher
from quickapp.common.time_provider import TimeProvider
from quickapp.config.application import ApplicationConfig
from quickapp.timestamp_tooling._current_timestamp_tool import _CurrentTimestampTool
from quickapp.timestamp_tooling._timestamp_annotation_transformer import (
    _TimestampAnnotationTransformer,
)
from quickapp.timestamp_tooling._timestamp_injection_transformer import (
    _TimestampInjectionTransformer,
)
from quickapp.timestamp_tooling._timestamp_metadata_enricher import _TimestampMetadataEnricher
from quickapp.timestamp_tooling._timezone_resolver import resolve_user_timezone
from quickapp.timestamp_tooling._tool_configs import CURRENT_TIMESTAMP_TOOL_CONFIG

logger = logging.getLogger(__name__)


class TimestampModule(Module):

    def configure(self, binder: Binder) -> None:
        binder.bind(_CurrentTimestampTool, to=_CurrentTimestampTool, scope=request_scope)
        binder.bind(
            _TimestampInjectionTransformer,
            to=_TimestampInjectionTransformer,
            scope=request_scope,
        )
        binder.bind(
            _TimestampAnnotationTransformer,
            to=_TimestampAnnotationTransformer,
            scope=request_scope,
        )

        logger.debug("TimestampModule configuration completed")

    @provider
    @request_scope
    def _provide_time_provider(self, timezone_header_value: TIMEZONE_HEADER_VALUE) -> TimeProvider:
        tz, label = resolve_user_timezone(timezone_header_value)
        return TimeProvider(tz=tz, label=label)

    @staticmethod
    def _is_timestamp_feature_enabled(app_config: ApplicationConfig) -> bool:
        features = app_config.features
        return features is not None and features.timestamp is not None

    @multiprovider
    def _provide_timestamp_tools(
        self,
        app_config: ApplicationConfig,
        tool_builder: AssistedBuilder[_CurrentTimestampTool],
    ) -> list[StagedBaseTool]:
        if not self._is_timestamp_feature_enabled(app_config):
            return []

        return [
            tool_builder.build(
                tool_config=CURRENT_TIMESTAMP_TOOL_CONFIG,
                name=CURRENT_TIMESTAMP_TOOL_CONFIG.open_ai_tool.function.name,
                description=CURRENT_TIMESTAMP_TOOL_CONFIG.open_ai_tool.function.description,
            )
        ]

    @multiprovider
    def _provide_message_transformers(
        self,
        app_config: ApplicationConfig,
        injection_transformer: ProviderOf[_TimestampInjectionTransformer],
    ) -> list[MessagesTransformer]:
        if not self._is_timestamp_feature_enabled(app_config):
            return []
        return [injection_transformer.get()]

    @multiprovider
    def _provide_pre_invocation_transformers(
        self,
        app_config: ApplicationConfig,
        annotation_transformer: _TimestampAnnotationTransformer,
    ) -> list[PreInvocationTransformer]:
        if not self._is_timestamp_feature_enabled(app_config):
            return []
        return [annotation_transformer]

    @multiprovider
    def _provide_enrichers(
        self,
        app_config: ApplicationConfig,
        time_provider: ProviderOf[TimeProvider],
    ) -> list[ToolCallResultEnricher]:
        if not self._is_timestamp_feature_enabled(app_config):
            return []
        return [_TimestampMetadataEnricher(time_provider.get())]
