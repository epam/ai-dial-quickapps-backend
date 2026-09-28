from typing import Annotated

from injector import inject

from quickapp.config.application import ApplicationConfig, StageDisplayLevel
from quickapp.shared.config_resolvers.stage_display_settings import StageDisplaySettings

PROPAGATE_SUB_STAGES = Annotated[bool, "PROPAGATE_SUB_STAGES"]


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

    def resolve_propagate_sub_stages(self) -> bool:
        """Nested sub-app stages. Unset app config defaults to on."""
        features = self.__app_config.features
        stage_display = features.stage_display if features is not None else None
        return stage_display.propagate_sub_stages if stage_display is not None else True
