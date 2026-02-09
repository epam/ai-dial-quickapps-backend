from injector import inject

from quickapp.common.base_initializer import StartupInitializer
from quickapp.skills.agent_skills_provider import AgentSkillsProvider


@inject
class _SkillsInitializer(StartupInitializer):

    def __init__(self, skills_provider: AgentSkillsProvider):
        self._skills_provider = skills_provider

    async def initialize(self) -> None:
        # Touch provider to ensure skills load at startup.
        self._skills_provider.get_skills_xml()
