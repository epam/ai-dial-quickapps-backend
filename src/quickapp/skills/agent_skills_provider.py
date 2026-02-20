import logging
import re
from typing import Any

import yaml
from injector import inject
from pydantic import BaseModel

from quickapp.common.abstract.base_prompt_provider import PromptPartProvider
from quickapp.config.predefined_content_provider import ContentType, PredefinedContentProvider

logger = logging.getLogger(__name__)


class SkillMetadata(BaseModel):
    """Metadata extracted from a skill file's YAML frontmatter."""

    name: str
    description: str
    license: str | None = None
    compatibility: str | None = None
    metadata: dict | None = None
    allowed_tools: list[str] | None = None


@inject
class AgentSkillsProvider(PromptPartProvider):
    """Loads predefined skills, parses YAML frontmatter, and provides XML metadata
    for the system prompt.
    """

    def __init__(self, provider: PredefinedContentProvider) -> None:
        self._xml_metadata: str = ""
        self._skills: list[SkillMetadata] = []
        self._skill_name_to_file: dict[str, str] = {}
        self._skill_content_cache: dict[str, str] = {}
        self._provider = provider
        self._load_skills()

    @staticmethod
    def _parse_frontmatter(content: str, file_name: str) -> SkillMetadata | None:
        """Parse YAML frontmatter delimited by ``---`` and return validated SkillMetadata."""
        frontmatter_pattern = r'^---\s*\n(.*?)\n---\s*\n'
        match = re.match(frontmatter_pattern, content, re.DOTALL)

        if not match:
            logger.warning(f"No YAML frontmatter found in {file_name}")
            return None

        try:
            parsed = yaml.safe_load(match.group(1))
        except yaml.YAMLError as exc:
            logger.error(f"Failed to parse YAML frontmatter in {file_name}: {exc}")
            return None

        if not isinstance(parsed, dict):
            logger.warning(f"YAML frontmatter is not a dictionary in {file_name}")
            return None

        # Normalize 'allowed-tools' hyphenated key to 'allowed_tools'
        if 'allowed-tools' in parsed:
            allowed_tools_value = parsed.pop('allowed-tools')
            if isinstance(allowed_tools_value, str):
                parsed['allowed_tools'] = allowed_tools_value.split()
            elif isinstance(allowed_tools_value, list):
                parsed['allowed_tools'] = allowed_tools_value
            else:
                logger.warning(f"Invalid allowed-tools format in {file_name}")

        name = parsed.get('name')
        description = parsed.get('description')

        if not name or not description:
            logger.warning(f"Missing required fields (name/description) in {file_name}")
            return None

        if len(name) > 64:
            logger.warning(f"Skill name exceeds 64 characters in {file_name}: {name}")
            return None

        if not re.match(r'^[a-z0-9]([a-z0-9-]*[a-z0-9])?$', name):
            logger.warning(
                f"Invalid skill name format in {file_name}: {name}"
                " (must be lowercase letters, numbers, hyphens; no leading/trailing hyphens)"
            )
            return None

        if len(description) > 1024:
            logger.warning(f"Description exceeds 1024 characters in {file_name}")
            return None

        skill_data: dict[str, Any] = {'name': name, 'description': description}

        if 'license' in parsed:
            skill_data['license'] = parsed['license']

        if 'compatibility' in parsed:
            compat = parsed['compatibility']
            if len(compat) > 500:
                logger.warning(f"Compatibility exceeds 500 characters in {file_name}, truncating")
                compat = compat[:500]
            skill_data['compatibility'] = compat

        if parsed.get('metadata'):
            skill_data['metadata'] = parsed['metadata']

        if 'allowed_tools' in parsed:
            skill_data['allowed_tools'] = parsed['allowed_tools']

        return SkillMetadata(**skill_data)

    def _generate_xml(self, skills: list[SkillMetadata]) -> str:
        """Generate XML representation of available skills for the system prompt."""
        if not skills:
            return ""

        xml_parts = ["<available_skills>"]

        for skill_metadata in skills:
            xml_parts.append("  <skill>")
            xml_parts.append(f"    <name>{self._escape_xml(skill_metadata.name)}</name>")
            xml_parts.append(
                f"    <description>{self._escape_xml(skill_metadata.description)}</description>"
            )
            if skill_metadata.license:
                xml_parts.append(
                    f"    <license>{self._escape_xml(skill_metadata.license)}</license>"
                )
            if skill_metadata.compatibility:
                xml_parts.append(
                    f"    <compatibility>{self._escape_xml(skill_metadata.compatibility)}</compatibility>"
                )
            if skill_metadata.allowed_tools:
                allowed_tools = " ".join(skill_metadata.allowed_tools)
                xml_parts.append(
                    f"    <allowed_tools>{self._escape_xml(allowed_tools)}</allowed_tools>"
                )
            if skill_metadata.metadata:
                xml_parts.append("    <metadata>")
                for key in sorted(skill_metadata.metadata.keys()):
                    value = (
                        ""
                        if skill_metadata.metadata[key] is None
                        else str(skill_metadata.metadata[key])
                    )
                    xml_parts.append(
                        f"      <entry key=\"{self._escape_xml(str(key))}\">{self._escape_xml(value)}</entry>"
                    )
                xml_parts.append("    </metadata>")
            xml_parts.append("  </skill>")

        xml_parts.append("</available_skills>")

        return "\n".join(xml_parts)

    @staticmethod
    def _escape_xml(text: str) -> str:
        """Escape XML special characters."""
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&apos;")
        )

    def _load_skills(self) -> None:
        """Load all skill files and generate XML metadata."""
        skill_names = self._provider.list_names(ContentType.SKILL)

        if not skill_names:
            logger.debug("No skills found in predefined content")
            return

        skills: list[SkillMetadata] = []
        skill_name_to_file: dict[str, str] = {}
        skill_content_cache: dict[str, str] = {}
        for file_stem in skill_names:
            try:
                logger.debug(f"Loading skill `{file_stem}`")
                content = self._provider.read_text(ContentType.SKILL, file_stem)
                metadata = self._parse_frontmatter(content, file_stem)
                if metadata:
                    skills.append(metadata)
                    if metadata.name not in skill_name_to_file:
                        skill_name_to_file[metadata.name] = file_stem
                        skill_content_cache[metadata.name] = content
                    else:
                        logger.warning(
                            "Duplicate skill name `%s` in `%s`; keeping first file `%s`",
                            metadata.name,
                            file_stem,
                            skill_name_to_file[metadata.name],
                        )
            except Exception as exc:
                logger.error(f"Failed to parse skill `{file_stem}`: {exc}")

        self._skills = skills
        self._skill_name_to_file = skill_name_to_file
        self._skill_content_cache = skill_content_cache
        self._xml_metadata = self._generate_xml(skills)
        logger.info(f"Loaded {len(skills)} skill(s)")

    def get_skills_xml(self) -> str:
        """Return XML metadata for all available skills."""
        return self._xml_metadata

    def get_prompt_part(self) -> str:
        """Return skills XML for inclusion in the system prompt."""
        return self.get_skills_xml()

    def get_skill_content(self, skill_name: str) -> str:
        """Return the full content of a skill file. Raises FileNotFoundError if not found."""
        if skill_name in self._skill_content_cache:
            return self._skill_content_cache[skill_name]
        raise FileNotFoundError(f"Skill not found: {skill_name}")
