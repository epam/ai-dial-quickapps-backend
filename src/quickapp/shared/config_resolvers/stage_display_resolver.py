from injector import inject

from quickapp.config.application import ApplicationConfig, StageDisplayLevel
from quickapp.shared.config_resolvers.stage_display_settings import StageDisplaySettings


@inject
class StageDisplayResolver:
    def __init__(
        self,
        settings: StageDisplaySettings,
        app_config: ApplicationConfig,
    ) -> None:
        self.__settings = settings
        self.__app_config = app_config

    def resolve(self) -> StageDisplayLevel:
        # Env override takes precedence over per-app config (unlike other resolvers).
        if self.__settings.stage_display_level is not None:
            return self.__settings.stage_display_level
        features = self.__app_config.features
        return features.stage_display.level if features is not None else StageDisplayLevel.INFO
