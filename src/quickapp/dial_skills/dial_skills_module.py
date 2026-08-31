import logging

from fastapi_injector import request_scope
from injector import Binder, Module, ProviderOf, multiprovider, singleton

from quickapp.common.base_initializer import CompletionInitializer
from quickapp.common.exceptions import InitializationException
from quickapp.common.preview import preview_module
from quickapp.dial_skills._dial_skill_initializer import _DialSkillInitializer
from quickapp.dial_skills._dial_skill_resolver import DialSkillResolver
from quickapp.dial_skills._dial_skills_client import _DialSkillsClient
from quickapp.dial_skills._dial_skills_context import _DialSkillsContext
from quickapp.dial_skills._settings import DialSkillsSettings

logger = logging.getLogger(__name__)


@preview_module
class DialSkillsModule(Module):

    def configure(self, binder: Binder) -> None:
        binder.bind(DialSkillsSettings, to=DialSkillsSettings, scope=singleton)
        binder.bind(_DialSkillsClient, to=_DialSkillsClient, scope=request_scope)
        binder.bind(DialSkillResolver, to=DialSkillResolver, scope=request_scope)
        binder.bind(_DialSkillsContext, to=_DialSkillsContext, scope=request_scope)
        binder.bind(_DialSkillInitializer, to=_DialSkillInitializer, scope=request_scope)
        logger.debug("DialSkillsModule configuration completed")

    @multiprovider
    def __provide_initializers(
        self, initializer_provider: ProviderOf[_DialSkillInitializer]
    ) -> list[CompletionInitializer]:
        return [initializer_provider.get()]

    @multiprovider
    def __provide_initialization_exceptions(
        self, context: _DialSkillsContext
    ) -> list[InitializationException]:
        return context.exceptions
