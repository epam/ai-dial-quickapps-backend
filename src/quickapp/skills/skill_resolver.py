from abc import ABC, abstractmethod

from pydantic import BaseModel, ConfigDict

from quickapp.common.exceptions import SkillInitializationException
from quickapp.config.skill import DialSkillConfig
from quickapp.skills.skills_provider import ResolvedSkill


class SkillResolution(BaseModel):
    """What one resolution pass produced, whatever source ran it.

    ``exceptions`` carries both per-URL failures and non-fatal warnings,
    distinguished by ``severity`` — resolving is best-effort, so a bad entry
    never costs the caller the good ones.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    resolved: list[ResolvedSkill]
    exceptions: list[SkillInitializationException]


class DialSkillResourceResolver(ABC):
    """Resolves DIAL ``skills/`` resources into validated skills.

    The abstraction exists so features that resolve a user's skill resources —
    today ``skills/invocation`` — depend on this contract rather than on
    ``skills/dial``'s concrete implementation. ``DialSkillsModule`` binds it.
    """

    @abstractmethod
    async def resolve(self, skill_configs: list[DialSkillConfig]) -> SkillResolution:
        """Resolve *skill_configs* into validated entries.

        Deduplicates by URL before fetching and by skill name afterwards
        (first configured wins). Never raises for a single bad entry — it
        lands in ``SkillResolution.exceptions`` instead.
        """
        ...
