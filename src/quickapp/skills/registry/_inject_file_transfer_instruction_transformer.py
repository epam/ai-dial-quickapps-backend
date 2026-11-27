from injector import ProviderOf, inject

from quickapp.common.abstract.tool_call_result_enricher import ToolCallResultEnricher
from quickapp.skills.registry._builtin_skill_instruction_injector import (
    BuiltinSkillInstructionInjector,
)
from quickapp.skills.registry.agent_skills_provider import AgentSkillsProvider

BUILTIN_FILE_TRANSFER_SKILL = "tool-call-file-parameter-formatting"


class _InjectFileTransferInstructionTransformer(BuiltinSkillInstructionInjector):
    """Injects the file-parameter formatting instruction as a synthetic skill-reader tool call."""

    @inject
    def __init__(
        self,
        skills_provider: AgentSkillsProvider,
        enrichers_provider: ProviderOf[list[ToolCallResultEnricher]],
    ):
        super().__init__(BUILTIN_FILE_TRANSFER_SKILL, skills_provider, enrichers_provider)
