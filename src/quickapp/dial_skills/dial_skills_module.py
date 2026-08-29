import logging

from fastapi_injector import request_scope
from injector import Binder, Module, ProviderOf, multiprovider, singleton

from quickapp.common.base_initializer import CompletionInitializer
from quickapp.common.exceptions import InitializationException
from quickapp.common.preview import preview_module
from quickapp.dial_skills._dial_skill_initializer import _DialSkillInitializer
from quickapp.dial_skills._dial_skill_resolver import DialSkillResolver
from quickapp.dial_skills._dial_skills_client import DialSkillsClient
from quickapp.dial_skills._dial_skills_context import _DialSkillsContext
from quickapp.dial_skills._settings import DialSkillsSettings
from quickapp.skills._skill import Skill

logger = logging.getLogger(__name__)


@preview_module
class DialSkillsModule(Module):
    """DI wiring for ``dial-skill`` sources.

    Preview-gated in two places, and both are needed. This marker drops the
    initializer and the client from the injector; ``@preview_model`` on
    ``DialSkillConfig`` strips the variant from the published schema and from
    the parsed config. Without the model marker, dropping the module alone
    would be silent: Chat's editor would keep offering ``dial-skill``, entries
    would still validate, nothing would resolve them, and no diagnostic would
    appear.
    """

    def configure(self, binder: Binder) -> None:
        binder.bind(DialSkillsSettings, to=DialSkillsSettings, scope=singleton)
        binder.bind(DialSkillsClient, to=DialSkillsClient, scope=request_scope)
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

    @multiprovider
    def __provide_skills(self, context: _DialSkillsContext) -> list[Skill]:
        return list(context.resolved_skills)
