import functools

from injector import inject

from quickapp.common.exceptions import SkillInitializationException
from quickapp.dial_skills._dial_skill_reader import DialSkillReader
from quickapp.dial_skills._dial_skills_context import _DialSkillsContext
from quickapp.skills import ResolvedSkillCandidate, SkillSource


@inject
class _DialSkillsSource(SkillSource):
    """Adapts ``_DialSkillsContext`` + ``DialSkillReader`` to ``SkillSource``.

    The only source with bundled-file capability today: each candidate's
    ``read_file`` is a closure over the specific ``ResolvedDialSkill`` and the
    shared ``DialSkillReader``, so ``SkillsRegistry`` never needs to see
    ``ResolvedDialSkill`` at all.
    """

    order = 20
    display_name = "DIAL skill resources"

    def __init__(self, context: _DialSkillsContext, reader: DialSkillReader) -> None:
        self._context = context
        self._reader = reader

    def get_candidates(self) -> list[ResolvedSkillCandidate]:
        return [
            ResolvedSkillCandidate(
                url=skill.url,
                metadata=skill.metadata,
                content=skill.content,
                read_file=functools.partial(self._reader.read_bundled_file, skill),
            )
            for skill in self._context.resolved_skills
        ]

    def report_exceptions(self, exceptions: list[SkillInitializationException]) -> None:
        self._context.extend_exceptions(exceptions)
