from injector import inject
from pydantic import SecretStr

from quickapp.common._di_types import DIAL_API_KEY
from quickapp.common.dial_core_client import DialCoreClient
from quickapp.common.dial_settings import DialSettings
from quickapp.common.tool_timeout_resolver import ToolTimeoutResolver


@inject
class DialCoreClientFactory:
    def __init__(
        self,
        dial_settings: DialSettings,
        api_key: DIAL_API_KEY,
        timeout_resolver: ToolTimeoutResolver,
    ):
        self._dial_settings: DialSettings = dial_settings
        self._api_key: DIAL_API_KEY = api_key
        self._timeout_resolver: ToolTimeoutResolver = timeout_resolver

    def create(
        self,
        api_key: SecretStr | str | None = None,
    ) -> DialCoreClient:
        return DialCoreClient(
            api_key=api_key if api_key is not None else self._api_key,
            base_url=self._dial_settings.url,
            timeout=self._timeout_resolver.resolve(),
        )
