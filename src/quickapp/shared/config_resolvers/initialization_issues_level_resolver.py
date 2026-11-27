from injector import inject

from quickapp.config.application import ApplicationConfig, InitializationIssueLevel
from quickapp.shared.config_resolvers.initialization_issues_settings import (
    InitializationIssuesSettings,
)


@inject
class InitializationIssuesLevelResolver:
    def __init__(
        self,
        settings: InitializationIssuesSettings,
        app_config: ApplicationConfig,
    ) -> None:
        self.__settings = settings
        self.__app_config = app_config

    def resolve(self) -> InitializationIssueLevel:
        # Per-app value overrides the env default.
        features = self.__app_config.features
        if features is not None and features.initialization_issues.level is not None:
            return features.initialization_issues.level
        return self.__settings.level
