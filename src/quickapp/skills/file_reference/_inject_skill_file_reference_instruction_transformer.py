import logging

from aidial_sdk.chat_completion import Message
from injector import ProviderOf, inject

from quickapp.common.abstract.tool_call_result_enricher import ToolCallResultEnricher
from quickapp.common.synthetic_injection.injection_enums import InjectionFrequency
from quickapp.common.synthetic_injection.synthetic_tool_call_injector import (
    SyntheticToolCallInjector,
)
from quickapp.common.tool_names import INTERNAL_SKILLS_READ_SKILL_TOOL_NAME
from quickapp.skills.registry.agent_skills_provider import AgentSkillsProvider

logger = logging.getLogger(__name__)

BUILTIN_SKILL_FILE_REFERENCE_SKILL = "tool-call-skill-file-references"


class _InjectSkillFileReferenceInstructionTransformer(SyntheticToolCallInjector):
    """Injects the skill-file-reference instruction as a synthetic ``read_skill`` call after
    the first USER message, exactly once per conversation.

    Unconditional on purpose: the text is static, so it sits in the prompt-cache prefix.
    """

    @inject
    def __init__(
        self,
        skills_provider: AgentSkillsProvider,
        enrichers_provider: ProviderOf[list[ToolCallResultEnricher]],
    ):
        super().__init__(enrichers_provider)
        self.__skills_provider = skills_provider

    async def get_tool_name(self) -> str:
        return INTERNAL_SKILLS_READ_SKILL_TOOL_NAME

    async def get_frequency(self, messages: list[Message]) -> InjectionFrequency:
        return InjectionFrequency.APPEND_IF_CHANGED

    async def get_arguments(self) -> dict:
        return {"skill_name": BUILTIN_SKILL_FILE_REFERENCE_SKILL}

    async def get_content(self, messages: list[Message]) -> str | None:
        try:
            return self.__skills_provider.get_skill_content(BUILTIN_SKILL_FILE_REFERENCE_SKILL)
        except (FileNotFoundError, ValueError) as e:
            logger.error("Builtin skill file reference skill not found, skipping injection: %s", e)
            return None
