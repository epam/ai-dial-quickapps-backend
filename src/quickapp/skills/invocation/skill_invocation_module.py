import logging

from fastapi_injector import request_scope
from injector import Binder, Module, ProviderOf, multiprovider, singleton

from quickapp.common.abstract.base_transformer import MessagesTransformer
from quickapp.common.base_initializer import CompletionInitializer
from quickapp.common.exceptions import InitializationException
from quickapp.common.preview import preview_module
from quickapp.skills.invocation._invoked_skills_context import _InvokedSkillsContext
from quickapp.skills.invocation._settings import SkillInvocationSettings
from quickapp.skills.invocation._skill_invocation_initializer import _SkillInvocationInitializer
from quickapp.skills.invocation._skill_invocation_injector import _SkillInvocationInjector
from quickapp.skills.skills_provider import SkillsProvider

logger = logging.getLogger(__name__)


@preview_module
class SkillInvocationModule(Module):
    """Wires skills a user invokes from a message, via ``custom_content.skills``.

    Preview-gated, matching ``DialSkillsModule``, whose ``DialSkillResolver`` it
    reuses.
    """

    def configure(self, binder: Binder) -> None:
        binder.bind(SkillInvocationSettings, to=SkillInvocationSettings, scope=singleton)
        binder.bind(_InvokedSkillsContext, to=_InvokedSkillsContext, scope=request_scope)
        binder.bind(
            _SkillInvocationInitializer, to=_SkillInvocationInitializer, scope=request_scope
        )
        binder.bind(_SkillInvocationInjector, to=_SkillInvocationInjector, scope=request_scope)
        logger.debug("SkillInvocationModule configuration completed")

    @multiprovider
    def __provide_initializers(
        self, initializer_provider: ProviderOf[_SkillInvocationInitializer]
    ) -> list[CompletionInitializer]:
        return [initializer_provider.get()]

    @multiprovider
    def __provide_initialization_exceptions(
        self, context: _InvokedSkillsContext
    ) -> list[InitializationException]:
        return context.exceptions

    @multiprovider
    def __provide_skill_providers(self, context: _InvokedSkillsContext) -> list[SkillsProvider]:
        return [context]

    @multiprovider
    def __provide_message_transformers(
        self, injector: _SkillInvocationInjector
    ) -> list[MessagesTransformer]:
        return [injector]
