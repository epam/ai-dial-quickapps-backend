import logging

from injector import inject

from quickapp.common.abstract.base_prompt_provider import PromptPartProvider
from quickapp.config.predefined_content_provider import ContentType, PredefinedContentProvider
from quickapp.skills._exceptions import SkillValidationError
from quickapp.skills._frontmatter import parse_frontmatter
from quickapp.skills._skill_metadata import SkillMetadata
from quickapp.skills._xml import generate_skills_xml

logger = logging.getLogger(__name__)


@inject
class AgentSkillsProvider(PromptPartProvider):
    """Loads predefined skills, parses YAML frontmatter, and provides XML metadata
    for the system prompt.
    """

    def __init__(self, provider: PredefinedContentProvider) -> None:
        self._xml_metadata: str = ""
        self._skills: list[SkillMetadata] = []
        self._provider = provider
        self._load_skills()

    def _load_skills(self) -> None:
        skill_names = self._provider.list_names(ContentType.SKILL)

        if not skill_names:
            logger.debug("No skills found in predefined content")
            return

        skills: list[SkillMetadata] = []
        for file_stem in skill_names:
            try:
                logger.debug(f"Loading skill `{file_stem}`")
                content = self._provider.read_text(ContentType.SKILL, file_stem)
                metadata = parse_frontmatter(content, file_stem)
            except SkillValidationError as exc:
                logger.warning(str(exc))
                continue
            except Exception as exc:
                logger.error(f"Failed to parse skill `{file_stem}`: {exc}")
                continue

            if metadata.name != file_stem:
                logger.warning(
                    "Skill name '%s' does not match directory name '%s'; skipping",
                    metadata.name,
                    file_stem,
                )
                continue
            skills.append(metadata)

        self._skills = skills
        self._xml_metadata = generate_skills_xml(skills)
        logger.info(f"Loaded {len(skills)} skill(s)")

    def get_skills_xml(self) -> str:
        """Return XML metadata for all available skills."""
        return self._xml_metadata

    async def get_prompt_part(self) -> str:
        """Return skills XML for inclusion in the system prompt."""
        return self.get_skills_xml()

    def get_skill_content(self, skill_name: str) -> str:
        """Return the full content of a skill file. Raises FileNotFoundError if not found."""
        try:
            return self._provider.read_text(ContentType.SKILL, skill_name)
        except KeyError:
            raise FileNotFoundError(f"Skill not found: {skill_name}")
