import logging

from fastapi_injector import request_scope
from injector import Binder, Module, multiprovider, provider, singleton

from quickapp.common.abstract.tool_call_result_processor import ToolCallResultProcessor
from quickapp.common.preview import preview_module
from quickapp.config.application import ApplicationConfig
from quickapp.tool_call_result_offload._large_response_processor import LargeResponseProcessor
from quickapp.tool_call_result_offload._settings import (
    ResolvedConfig,
    ToolCallResultOffloadSettings,
)

logger = logging.getLogger(__name__)


@preview_module
class ToolCallResultOffloadModule(Module):

    def configure(self, binder: Binder) -> None:
        binder.bind(
            ToolCallResultOffloadSettings, to=ToolCallResultOffloadSettings, scope=singleton
        )
        binder.bind(LargeResponseProcessor, to=LargeResponseProcessor, scope=request_scope)
        logger.debug("ToolCallResultOffloadModule configuration completed")

    @request_scope
    @provider
    def _provide_offload_config(
        self,
        settings: ToolCallResultOffloadSettings,
        app_config: ApplicationConfig,
    ) -> ResolvedConfig:
        # Per-app config is None when the preview feature is disabled or not configured —
        # in that case every field falls back to the global env-based setting.
        # Each field is resolved independently: null means "use env default".
        app = app_config.tool_defaults.tool_call_result_offload
        return ResolvedConfig(
            enabled=(
                app.enabled if app is not None and app.enabled is not None else settings.enabled
            ),
            size_threshold=(
                app.size_threshold
                if app is not None and app.size_threshold is not None
                else settings.size_threshold
            ),
            excluded_tools=frozenset(
                app.excluded_tools
                if app is not None and app.excluded_tools is not None
                else settings.excluded_tools
            ),
        )

    @multiprovider
    def _provide_processors(
        self,
        processor: LargeResponseProcessor,
    ) -> list[ToolCallResultProcessor]:
        return [processor]
