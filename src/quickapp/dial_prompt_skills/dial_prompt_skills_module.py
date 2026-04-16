import logging

from fastapi_injector import request_scope
from injector import Binder, Module

from quickapp.common.preview import preview_module
from quickapp.dial_prompt_skills._dial_prompt_skill_resolver import DialPromptSkillResolver

logger = logging.getLogger(__name__)


@preview_module
class DialPromptSkillsModule(Module):

    def configure(self, binder: Binder) -> None:
        binder.bind(DialPromptSkillResolver, to=DialPromptSkillResolver, scope=request_scope)
        logger.debug("DialPromptSkillsModule configuration completed")
