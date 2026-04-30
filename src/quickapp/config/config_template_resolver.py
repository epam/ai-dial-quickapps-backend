from abc import ABC, abstractmethod

from quickapp.config.application import ApplicationConfig


class ConfigResolver(ABC):
    """Resolves a raw ``ApplicationConfig`` (predefined references, overrides, etc.)
    into a fully concrete ``ApplicationConfig`` ready for downstream initializers.

    The concrete implementation lives in
    ``quickapp.predefined_tooling.PredefinedConfigResolver`` and is bound to this
    abstract type by ``PredefinedToolingModule``. Consumers depend on the abstract
    type so the ``application/`` layer does not import from feature modules.
    """

    @abstractmethod
    def resolve_config(self, raw_config: ApplicationConfig) -> ApplicationConfig: ...
