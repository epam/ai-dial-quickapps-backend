import logging

from injector import Binder, Module, ProviderOf, multiprovider, singleton

from quickapp.common.base_initializer import StartupInitializer
from quickapp.configuration_support import _Controller, _Initializer

logger = logging.getLogger(__name__)


class ConfigurationSupportApiModule(Module):

    def configure(self, binder: Binder) -> None:
        binder.bind(_Controller, _Controller, scope=singleton)

    @multiprovider
    def __provide_initializers(
        self, initializer_provider: ProviderOf[_Initializer]
    ) -> list[StartupInitializer]:
        return [initializer_provider.get()]
