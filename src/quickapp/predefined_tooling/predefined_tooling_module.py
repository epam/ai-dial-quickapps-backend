import logging

from fastapi_injector import request_scope
from injector import Binder, Module, ProviderOf, multiprovider, singleton

from quickapp.common.base_initializer import CompletionInitializer
from quickapp.common.exceptions import InitializationException
from quickapp.config.config_template_resolver import ConfigResolver
from quickapp.predefined_tooling._dial_system_prompt_initializer import _DialSystemPromptInitializer
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
        binder.bind(
            _DialSystemPromptInitializer, to=_DialSystemPromptInitializer, scope=request_scope
        )
        logger.debug("PredefinedToolingModule configuration completed")

    @multiprovider
    def __provide_initializers(
        self, initializer_provider: ProviderOf[_DialSystemPromptInitializer]
    ) -> list[CompletionInitializer]:
        return [initializer_provider.get()]

    @multiprovider
    def __provide_initialization_exceptions(
        self, context: _PredefinedToolingContext
    ) -> list[InitializationException]:
        return context.exceptions
