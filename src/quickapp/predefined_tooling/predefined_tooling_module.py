import logging

from fastapi_injector import request_scope
from injector import Binder, Module, multiprovider, singleton

from quickapp.common.exceptions import InitializationException
from quickapp.config.config_template_resolver import ConfigResolver
from quickapp.predefined_tooling._predefined_config_resolver import PredefinedConfigResolver
from quickapp.predefined_tooling._predefined_tooling_context import _PredefinedToolingContext

logger = logging.getLogger(__name__)


class PredefinedToolingModule(Module):

    def configure(self, binder: Binder) -> None:
        binder.bind(_PredefinedToolingContext, to=_PredefinedToolingContext, scope=request_scope)
        binder.bind(PredefinedConfigResolver, to=PredefinedConfigResolver, scope=singleton)
        binder.bind(
            ConfigResolver, to=PredefinedConfigResolver, scope=singleton  # type: ignore[type-abstract]
        )
        logger.debug("PredefinedToolingModule configuration completed")

    @multiprovider
    def __provide_initialization_exceptions(
        self, context: _PredefinedToolingContext
    ) -> list[InitializationException]:
        return context.exceptions
