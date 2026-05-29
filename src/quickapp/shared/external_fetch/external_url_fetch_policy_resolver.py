from typing import Literal

from injector import inject

from quickapp.config.application import ApplicationConfig
from quickapp.shared.external_fetch.external_fetch_settings import ExternalFetchSettings
from quickapp.shared.external_fetch.host_pattern_match import match_host

PolicyReason = Literal["admin", "builder", "allowed"]
HostReason = Literal["admin_allowlist", "builder_allowlist", "allowed"]
DisabledReason = Literal["admin", "builder", "admin_allowlist", "builder_allowlist"]


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
        if not self.__settings.enabled:
            return "admin"
        features = self.__app_config.features
        if features is not None and features.external_url_fetch.enabled is False:
            return "builder"
        return "allowed"

    def resolve_host(self, host: str) -> HostReason:
        admin_list = self.__settings.host_allowlist
        if admin_list is not None and not match_host(host, admin_list):
            return "admin_allowlist"
        features = self.__app_config.features
        builder_list = features.external_url_fetch.host_allowlist if features is not None else None
        if builder_list is not None and not match_host(host, builder_list):
            return "builder_allowlist"
        return "allowed"
