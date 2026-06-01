from fastapi_injector import request_scope
from injector import Binder, Module, provider, singleton

from quickapp.config.application import StageDisplayLevel
from quickapp.shared.config_resolvers.file_loading_settings import FileLoadingSettings
from quickapp.shared.config_resolvers.file_loading_size_limit_resolver import (
    FileLoadingSizeLimitResolver,
)
from quickapp.shared.config_resolvers.stage_display_resolver import StageDisplayResolver
from quickapp.shared.config_resolvers.stage_display_settings import StageDisplaySettings
from quickapp.shared.config_resolvers.tool_timeout_resolver import ToolTimeoutResolver
from quickapp.shared.config_resolvers.tool_timeout_settings import ToolSettings


class ConfigResolversModule(Module):
    def configure(self, binder: Binder) -> None:
        binder.bind(ToolSettings, to=ToolSettings, scope=singleton)
        binder.bind(ToolTimeoutResolver, to=ToolTimeoutResolver, scope=request_scope)
        binder.bind(FileLoadingSettings, to=FileLoadingSettings, scope=singleton)
        binder.bind(
            FileLoadingSizeLimitResolver, to=FileLoadingSizeLimitResolver, scope=request_scope
        )
        binder.bind(StageDisplaySettings, to=StageDisplaySettings, scope=singleton)
        binder.bind(StageDisplayResolver, to=StageDisplayResolver, scope=request_scope)

    @provider
    def __provide_stage_display_level(self, resolver: StageDisplayResolver) -> StageDisplayLevel:
        return resolver.resolve()
