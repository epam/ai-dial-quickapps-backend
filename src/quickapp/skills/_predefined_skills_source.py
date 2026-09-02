from injector import inject

from quickapp.common.exceptions import SkillInitializationException
from quickapp.skills.agent_skills_provider import AgentSkillsProvider
from quickapp.skills.skill_source import ResolvedSkillCandidate, SkillSource


@inject
class _PredefinedSkillsSource(SkillSource):
    """Adapts ``AgentSkillsProvider`` to ``SkillSource``.

    Predefined skills always win against every *other* source
    (``order = 0``, the lowest value in practice); ``report_exceptions``
    no-ops rather than growing ``AgentSkillsProvider`` — which stays exactly
    the "pure data store" its own docstring promises — with collision
    handling. Two predefined skills sharing a name is a same-source
    collision this no-op would silently swallow, but that is
    ``AgentSkillsProvider``'s own data-quality concern (a content-authoring
    mistake at build time), not something a per-request merge adapter should
    police.
    """

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
