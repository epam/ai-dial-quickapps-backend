import logging

from aidial_sdk.chat_completion import Message
from injector import ProviderOf

from quickapp.common.abstract.tool_call_result_enricher import ToolCallResultEnricher
from quickapp.common.synthetic_injection.injection_enums import InjectionFrequency
from quickapp.common.synthetic_injection.synthetic_tool_call_injector import (
    SyntheticToolCallInjector,
)
from quickapp.skills.registry._tool_configs import SKILL_READER_TOOL_NAME
from quickapp.skills.registry.agent_skills_provider import AgentSkillsProvider

logger = logging.getLogger(__name__)


class BuiltinSkillInstructionInjector(SyntheticToolCallInjector):
    """Injects a built-in predefined skill as a synthetic ``read_skill`` call after the first
    USER message, exactly once per conversation.

    Subclasses only name the skill and declare their own ``@inject`` constructor.
    """

    def __init__(
        self,
        skill_name: str,
        skills_provider: AgentSkillsProvider,
        enrichers_provider: ProviderOf[list[ToolCallResultEnricher]],
    ):
        super().__init__(enrichers_provider)
        self.__skill_name = skill_name
        self.__skills_provider = skills_provider

    async def get_tool_name(self) -> str:
        return SKILL_READER_TOOL_NAME

    async def get_frequency(self, messages: list[Message]) -> InjectionFrequency:
        return InjectionFrequency.APPEND_IF_CHANGED

    async def get_arguments(self) -> dict:
        return {"skill_name": self.__skill_name}

    async def get_content(self, messages: list[Message]) -> str | None:
        try:
            return self.__skills_provider.get_skill_content(self.__skill_name)
        except (FileNotFoundError, ValueError) as e:
            logger.error(
                "Builtin skill '%s' not found, skipping injection: %s", self.__skill_name, e
            )
            return None
