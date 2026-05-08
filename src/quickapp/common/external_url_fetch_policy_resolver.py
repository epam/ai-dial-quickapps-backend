from typing import Literal

from injector import inject

from quickapp.common.external_fetch_settings import ExternalFetchSettings
from quickapp.config.application import ApplicationConfig

PolicyReason = Literal["admin", "builder", "allowed"]


@inject
class ExternalUrlFetchPolicyResolver:
    """Combines admin (env) and builder (per-app) gates into a single effective flag."""

    def __init__(
        self,
        settings: ExternalFetchSettings,
        app_config: ApplicationConfig,
    ) -> None:
        self.__settings = settings
        self.__app_config = app_config

    def resolve_reason(self) -> PolicyReason:
        if not self.__settings.allow:
            return "admin"
        features = self.__app_config.features
        if features is not None and features.external_url_fetch.enabled is False:
            return "builder"
        return "allowed"
