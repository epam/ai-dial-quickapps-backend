from injector import inject

from quickapp.common.exceptions import SkillInitializationException
from quickapp.skills.agent_skills_provider import AgentSkillsProvider
from quickapp.skills.skill_source import ResolvedSkillCandidate, SkillSource


@inject
class _PredefinedSkillsSource(SkillSource):
    """Adapts ``AgentSkillsProvider`` to ``SkillSource``. Predefined skills
    always win (``order = 0``), so ``report_exceptions`` no-ops."""

    order = 0
    display_name = "predefined skills"

    def __init__(self, provider: AgentSkillsProvider) -> None:
        self._provider = provider

    def get_candidates(self) -> list[ResolvedSkillCandidate]:
        contents = self._provider.get_all_skill_contents()
        return [
            ResolvedSkillCandidate(
                url=f"predefined:{metadata.name}",
                metadata=metadata,
                content=contents[metadata.name],
            )
            for metadata in self._provider.get_all_skills()
        ]

    def report_exceptions(self, exceptions: list[SkillInitializationException]) -> None:
        pass
