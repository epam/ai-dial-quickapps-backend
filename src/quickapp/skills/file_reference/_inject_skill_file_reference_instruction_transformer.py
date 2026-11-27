from injector import ProviderOf, inject

from quickapp.common.abstract.tool_call_result_enricher import ToolCallResultEnricher
from quickapp.skills.registry import BuiltinSkillInstructionInjector
from quickapp.skills.registry.agent_skills_provider import AgentSkillsProvider

BUILTIN_SKILL_FILE_REFERENCE_SKILL = "tool-call-skill-file-references"


class _InjectSkillFileReferenceInstructionTransformer(BuiltinSkillInstructionInjector):
    """Injects the skill-file-reference instruction as a synthetic ``read_skill`` call.

    Unconditional on purpose: the text is static, so it sits in the prompt-cache prefix.
    """

    @inject
    def __init__(
        self,
        skills_provider: AgentSkillsProvider,
        enrichers_provider: ProviderOf[list[ToolCallResultEnricher]],
    ):
        super().__init__(BUILTIN_SKILL_FILE_REFERENCE_SKILL, skills_provider, enrichers_provider)
