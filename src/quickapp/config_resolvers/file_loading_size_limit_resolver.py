from injector import inject

from quickapp.config.application import ApplicationConfig
from quickapp.config_resolvers.file_loading_settings import FileLoadingSettings


@inject
class FileLoadingSizeLimitResolver:
    def __init__(
        self,
        settings: FileLoadingSettings,
        app_config: ApplicationConfig,
    ) -> None:
        self.__settings = settings
        self.__app_config = app_config

    def resolve(self) -> int:
        features = self.__app_config.features
        override = features.file_loading.size_limit if features is not None else None
        return override if override is not None else self.__settings.size_limit
