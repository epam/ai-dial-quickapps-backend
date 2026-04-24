import logging

from injector import inject

from quickapp.config.predefined_content_provider import ContentType, PredefinedContentProvider
from quickapp.skills._exceptions import SkillValidationError
from quickapp.skills._frontmatter import parse_frontmatter
from quickapp.skills._skill_metadata import SkillMetadata

logger = logging.getLogger(__name__)


@inject
class AgentSkillsProvider:
    """Pure data store for predefined skills.

    Loads skills at startup, parses frontmatter, and exposes metadata and content.
    Does not generate XML — that is the responsibility of ``SkillsRegistry``.
    """

    def __init__(self, provider: PredefinedContentProvider) -> None:
        self._skills: list[SkillMetadata] = []
        self._contents: dict[str, str] = {}
        self._provider = provider
        self._load_skills()

    def _load_skills(self) -> None:
        skill_names = self._provider.list_names(ContentType.SKILL)

        if not skill_names:
            logger.debug("No skills found in predefined content")
            return

        skills: list[SkillMetadata] = []
        contents: dict[str, str] = {}
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
            contents[metadata.name] = content

        self._skills = skills
        self._contents = contents
        logger.info(f"Loaded {len(skills)} skill(s)")

    def get_all_skills(self) -> list[SkillMetadata]:
        """Return the cached list of predefined skill metadata."""
        return self._skills

    def get_all_skill_contents(self) -> dict[str, str]:
        """Return ``{name: full_content}`` for all predefined skills."""
        return self._contents

    def get_skill_content(self, skill_name: str) -> str:
        """Return the full content of a skill file. Raises FileNotFoundError if not found."""
        try:
            return self._contents[skill_name]
        except KeyError:
            raise FileNotFoundError(f"Skill not found: {skill_name}")
