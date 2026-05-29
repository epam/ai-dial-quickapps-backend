from injector import inject

from quickapp.config.application import ApplicationConfig
from quickapp.config_resolvers.tool_timeout_settings import ToolSettings


@inject
class ToolTimeoutResolver:
    def __init__(
        self,
        settings: ToolSettings,
        app_config: ApplicationConfig,
    ) -> None:
        self.__settings = settings
        self.__app_config = app_config

    def resolve(self) -> float:
        app_override = self.__app_config.tool_defaults.timeout_seconds
        if app_override is not None:
            return app_override
        return self.__settings.default_tool_timeout_seconds
