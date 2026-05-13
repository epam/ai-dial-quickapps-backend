import logging

from aidial_sdk.chat_completion import Message
from injector import ProviderOf, inject

from quickapp.common.abstract.tool_call_result_enricher import ToolCallResultEnricher
from quickapp.common.synthetic_injection.injection_enums import InjectionFrequency
from quickapp.common.synthetic_injection.synthetic_tool_call_injector import (
    SyntheticToolCallInjector,
)
from quickapp.skills._tool_configs import SKILL_READER_TOOL_NAME
from quickapp.skills.agent_skills_provider import AgentSkillsProvider

logger = logging.getLogger(__name__)

BUILTIN_FILE_TRANSFER_SKILL = "tool-call-file-parameter-formatting"


class _InjectFileTransferInstructionTransformer(SyntheticToolCallInjector):
    """Injects a synthetic skill-reader tool call after the first USER message,
    exactly once per conversation."""

    @inject
    def __init__(
        self,
        skills_provider: AgentSkillsProvider,
        enrichers_provider: ProviderOf[list[ToolCallResultEnricher]],
    ):
        super().__init__(enrichers_provider)
        self.__skills_provider = skills_provider

    async def get_tool_name(self) -> str:
        return SKILL_READER_TOOL_NAME

    async def get_frequency(self, messages: list[Message]) -> InjectionFrequency:
        return InjectionFrequency.APPEND_IF_CHANGED

    async def get_arguments(self) -> dict:
        return {"skill_name": BUILTIN_FILE_TRANSFER_SKILL}

    async def get_content(self, messages: list[Message]) -> str | None:
        try:
            return self.__skills_provider.get_skill_content(BUILTIN_FILE_TRANSFER_SKILL)
        except (FileNotFoundError, ValueError) as e:
            logger.error("Builtin file transfer skill not found, skipping injection: %s", e)
            return None
