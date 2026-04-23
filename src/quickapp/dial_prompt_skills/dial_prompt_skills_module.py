import logging

from fastapi_injector import request_scope
from injector import Binder, Module, ProviderOf, multiprovider

from quickapp.common.base_initializer import CompletionInitializer
from quickapp.common.exceptions import InitializationException
from quickapp.common.preview import preview_module
from quickapp.dial_prompt_skills._dial_prompt_skill_initializer import _DialPromptSkillInitializer
from quickapp.dial_prompt_skills._dial_prompt_skill_resolver import DialPromptSkillResolver
from quickapp.dial_prompt_skills._dial_prompt_skills_context import _DialPromptSkillsContext

logger = logging.getLogger(__name__)


@preview_module
class DialPromptSkillsModule(Module):

    def configure(self, binder: Binder) -> None:
        binder.bind(DialPromptSkillResolver, to=DialPromptSkillResolver, scope=request_scope)
        binder.bind(_DialPromptSkillsContext, to=_DialPromptSkillsContext, scope=request_scope)
        binder.bind(
            _DialPromptSkillInitializer, to=_DialPromptSkillInitializer, scope=request_scope
        )
        logger.debug("DialPromptSkillsModule configuration completed")

    @multiprovider
    def __provide_initializers(
        self, initializer_provider: ProviderOf[_DialPromptSkillInitializer]
    ) -> list[CompletionInitializer]:
        return [initializer_provider.get()]

    @multiprovider
    def __provide_initialization_exceptions(
        self, context: _DialPromptSkillsContext
    ) -> list[InitializationException]:
        return list(context.exceptions)
