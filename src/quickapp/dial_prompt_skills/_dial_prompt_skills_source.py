from injector import inject

from quickapp.common.exceptions import SkillInitializationException
from quickapp.dial_prompt_skills._dial_prompt_skills_context import _DialPromptSkillsContext
from quickapp.skills import ResolvedSkillCandidate, SkillSource


@inject
class _DialPromptSkillsSource(SkillSource):
    """Adapts ``_DialPromptSkillsContext`` to ``SkillSource``. Prompt skills
    are single-document, so candidates get no ``reader``."""

    order = 10
    display_name = "DIAL prompt skills"

    def __init__(self, context: _DialPromptSkillsContext) -> None:
        self._context = context

    def get_candidates(self) -> list[ResolvedSkillCandidate]:
        return [
            ResolvedSkillCandidate(url=skill.url, metadata=skill.metadata, content=skill.content)
            for skill in self._context.resolved_skills
        ]

    def report_exceptions(self, exceptions: list[SkillInitializationException]) -> None:
        self._context.extend_exceptions(exceptions)
