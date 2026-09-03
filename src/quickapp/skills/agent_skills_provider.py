import logging

from injector import inject

from quickapp.config.predefined_content_provider import ContentType, PredefinedContentProvider
from quickapp.skills._exceptions import SkillValidationError
from quickapp.skills._frontmatter import parse_frontmatter
from quickapp.skills._skill_metadata import SkillMetadata
from quickapp.skills.skills_provider import ResolvedSkill, SkillsProvider

logger = logging.getLogger(__name__)


@inject
class AgentSkillsProvider(SkillsProvider):
    """Data store for predefined skills, and the ``SkillsProvider`` for them.

    Loads skills at startup and parses frontmatter. Predefined skills are
    single-document (no ``reader``) and always win a name collision
    (``order = 0``).
    """

    order = 0
    display_name = "predefined skills"

    def __init__(self, provider: PredefinedContentProvider) -> None:
        self._resolved_skills: list[ResolvedSkill] = []
        self._by_name: dict[str, ResolvedSkill] = {}
        self._provider = provider
        self._load_skills()

    def _load_skills(self) -> None:
        skill_names = self._provider.list_names(ContentType.SKILL)

        if not skill_names:
            logger.debug("No skills found in predefined content")
            return

        skills: list[ResolvedSkill] = []
        for file_stem in skill_names:
            try:
                logger.debug(f"Loading skill `{file_stem}`")
                content = self._provider.read_text(ContentType.SKILL, file_stem)
                parsed = parse_frontmatter(content, file_stem)
            except SkillValidationError as exc:
                logger.warning(str(exc))
                continue
            except Exception as exc:
                logger.error(f"Failed to parse skill `{file_stem}`: {exc}")
                continue

            metadata = parsed.metadata
            for warning in parsed.warnings:
                logger.warning("Skill '%s': %s", file_stem, warning)

            if metadata.name != file_stem:
                logger.warning(
                    "Skill name '%s' does not match directory name '%s'; loading anyway",
                    metadata.name,
                    file_stem,
                )
            skills.append(
                ResolvedSkill(url=f"predefined:{metadata.name}", metadata=metadata, content=content)
            )

        self._resolved_skills = skills
        self._by_name = {skill.metadata.name: skill for skill in skills}
        # DEBUG: superseded at INFO by the request-initialized lifecycle event.
        logger.debug("Loaded %d skill(s)", len(skills))

    @property
    def resolved_skills(self) -> list[ResolvedSkill]:
        return self._resolved_skills

    def get_all_skills(self) -> list[SkillMetadata]:
        """Return the cached list of predefined skill metadata."""
        return [skill.metadata for skill in self._resolved_skills]

    def get_skill_content(self, skill_name: str) -> str:
        """Return the full content of a skill file. Raises FileNotFoundError if not found."""
        try:
            return self._by_name[skill_name].content
        except KeyError:
            raise FileNotFoundError(f"Skill not found: {skill_name}")
