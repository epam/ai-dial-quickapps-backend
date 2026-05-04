from injector import inject

from quickapp.common.file_loader_settings import FileLoaderSettings
from quickapp.config.application import ApplicationConfig


@inject
class FileLoaderSizeLimitResolver:
    def __init__(
        self,
        settings: FileLoaderSettings,
        app_config: ApplicationConfig,
    ) -> None:
        self.__settings = settings
        self.__app_config = app_config

    def resolve(self) -> int:
        features = self.__app_config.features
        override = features.file_loader.size_limit if features is not None else None
        return override if override is not None else self.__settings.size_limit
