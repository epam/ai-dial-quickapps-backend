import logging
import re
from pathlib import Path
from typing import List, Optional

from injector import inject
from pydantic import BaseModel

from quickapp.common.abstract.base_prompt_provider import PromptPartProvider
from quickapp.config.config_template_resolver import PredefinedSettings

logger = logging.getLogger(__name__)


class SkillMetadata(BaseModel):
    """Metadata extracted from a skill file's YAML frontmatter (per spec)."""

    # Required fields
    name: str  # Max 64 chars, lowercase letters, numbers, hyphens only
    description: str  # Max 1024 chars, non-empty

    # Optional fields
    license: Optional[str] = None  # License name or reference
    compatibility: Optional[str] = None  # Max 500 chars
    metadata: Optional[dict] = None  # Arbitrary key-value mapping
    allowed_tools: Optional[List[str]] = None  # Space-delimited tools list


@inject
class AgentSkillsProvider(PromptPartProvider):
    """
    Provider for agent skills. Loads skills from `config/predefined/skills/`,
    parses YAML frontmatter, provides XML metadata, and reads skill file contents.

    Implements PromptPartProvider to contribute skills XML to the system prompt.
    """

    def __init__(self, predefined_settings: PredefinedSettings) -> None:
        self._xml_metadata: str = ""
        self._skills_dir: Optional[Path] = None
        self._skills: List[SkillMetadata] = []
        self._skill_name_to_file: dict[str, str] = {}
        self._skill_content_cache: dict[str, str] = {}  # Cache skill file contents
        self.__predefined_settings = predefined_settings
        self._load_skills()

    def _get_skills_directory(self) -> Path:
        """Get the skills directory path."""
        if self._skills_dir is not None:
            return self._skills_dir

        predefined_base = self.__predefined_settings.base_path
        if predefined_base:
            self._skills_dir = Path(predefined_base) / "skills"
        else:
            # Calculate from common folder: src/quickapp/common -> config/predefined/skills
            project_root = Path(__file__).parents[3]
            self._skills_dir = project_root / "config" / "predefined" / "skills"

        return self._skills_dir

    @staticmethod
    def _parse_frontmatter(content: str, file_name: str) -> Optional[SkillMetadata]:
        """
        Parse YAML frontmatter from markdown content.
        Expected format per spec:
        ---
        name: skill-name
        description: Brief description
        license: MIT
        compatibility: Requires Python 3.8+
        metadata:
          key1: value1
          key2: value2
        allowed-tools: tool1 tool2 tool3
        ---

        Spec fields:
        - name (Required): Max 64 chars, lowercase/numbers/hyphens, no leading/trailing hyphens
        - description (Required): Max 1024 chars, non-empty
        - license (Optional): License name or reference
        - compatibility (Optional): Max 500 chars, environment requirements
        - metadata (Optional): Arbitrary key-value mapping
        - allowed-tools (Optional): Space-delimited list of tools
        """
        # Match YAML frontmatter between --- delimiters
        frontmatter_pattern = r'^---\s*\n(.*?)\n---\s*\n'
        match = re.match(frontmatter_pattern, content, re.DOTALL)

        if not match:
            logger.warning(f"No YAML frontmatter found in {file_name}")
            return None

        frontmatter_text = match.group(1)

        # Simple YAML parsing (without external dependency)
        parsed: dict = {}
        current_dict_key = None

        for line in frontmatter_text.split('\n'):
            stripped = line.strip()
            if not stripped:
                continue

            # Check if this is a nested key-value under a dict (e.g., metadata)
            if current_dict_key and line.startswith('  ') and ':' in stripped:
                key, value = stripped.split(':', 1)
                parsed[current_dict_key][key.strip()] = value.strip()
                continue
            else:
                current_dict_key = None

            if ':' in stripped:
                key, value = stripped.split(':', 1)
                key = key.strip()
                value = value.strip()

                # Handle metadata dict (nested structure)
                if key == 'metadata' and not value:
                    parsed[key] = {}
                    current_dict_key = key
                # Handle allowed-tools as space-delimited list
                elif key == 'allowed-tools' and value:
                    parsed['allowed_tools'] = value.split()
                # Handle other fields if they have values
                elif value:
                    parsed[key] = value

        # Extract and validate required fields
        name = parsed.get('name')
        description = parsed.get('description')

        if not name or not description:
            logger.warning(f"Missing required fields (name/description) in {file_name}")
            return None

        # Validate name format: lowercase letters, numbers, hyphens; max 64 chars; no leading/trailing hyphens
        if len(name) > 64:
            logger.warning(f"Skill name exceeds 64 characters in {file_name}: {name}")
            return None

        if not re.match(r'^[a-z0-9]([a-z0-9-]*[a-z0-9])?$', name):
            logger.warning(
                f"Invalid skill name format in {file_name}: {name} (must be lowercase letters, numbers, hyphens only; no leading/trailing hyphens)"
            )
            return None

        # Validate description: max 1024 chars, non-empty
        if len(description) > 1024:
            logger.warning(f"Description exceeds 1024 characters in {file_name}")
            return None

        # Build SkillMetadata with only fields present in frontmatter (per spec)
        skill_data = {'name': name, 'description': description}

        # Add optional fields only if they exist in frontmatter
        if 'license' in parsed:
            skill_data['license'] = parsed['license']

        if 'compatibility' in parsed:
            compat = parsed['compatibility']
            if len(compat) > 500:
                logger.warning(f"Compatibility exceeds 500 characters in {file_name}, truncating")
                compat = compat[:500]
            skill_data['compatibility'] = compat

        if 'metadata' in parsed and parsed['metadata']:
            skill_data['metadata'] = parsed['metadata']

        if 'allowed_tools' in parsed:
            skill_data['allowed_tools'] = parsed['allowed_tools']

        return SkillMetadata(**skill_data)

    def _generate_xml(self, skills: List[SkillMetadata]) -> str:
        """Generate XML format for available skills.

        Args:
            skills: List of SkillMetadata
        """
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
        skills_dir = self._get_skills_directory()

        if not skills_dir.exists() or not skills_dir.is_dir():
            logger.debug(f"No skills directory found at `{skills_dir}`")
            return

        md_files: List[Path] = sorted(skills_dir.glob("*.md"))
        if not md_files:
            logger.debug(f"No `.md` files found in `{skills_dir}`")
            return

        skills: List[SkillMetadata] = []
        skill_name_to_file: dict[str, str] = {}
        skill_content_cache: dict[str, str] = {}
        for md in md_files:
            try:
                logger.debug(f"Loading skill file `{md}`")
                content = md.read_text(encoding="utf-8")
                metadata = self._parse_frontmatter(content, md.name)
                if metadata:
                    skills.append(metadata)
                    if metadata.name not in skill_name_to_file:
                        skill_name_to_file[metadata.name] = md.name
                        skill_content_cache[metadata.name] = content  # Cache the content
                    else:
                        logger.warning(
                            "Duplicate skill name `%s` in `%s`; keeping first file `%s`",
                            metadata.name,
                            md.name,
                            skill_name_to_file[metadata.name],
                        )
            except Exception as exc:
                logger.error(f"Failed to parse skill file `{md}`: {exc}")

        self._skills = skills
        self._skill_name_to_file = skill_name_to_file
        self._skill_content_cache = skill_content_cache
        self._xml_metadata = self._generate_xml(skills)
        logger.info(f"Loaded {len(skills)} skill(s)")

    def get_skills_xml(self) -> str:
        """
        Public method: Returns XML metadata for all available skills.
        Use this to inject skill metadata into the agent's system prompt.
        """
        return self._xml_metadata

    def get_prompt_part(self) -> str:
        """
        Implementation of PromptPartProvider interface.
        Returns XML metadata for all available skills to be included in the system prompt.

        Returns:
            str: XML representation of available skills, or empty string if no skills.
        """
        return self.get_skills_xml()

    def get_skill_content(self, skill_name: str) -> str:
        """
        Public method: Read and return the full content of a specific skill file.

        Args:
            skill_name: The skill name from metadata (e.g., 'builtin-file-transfer')

        Returns:
            The full content of the skill file

        Raises:
            FileNotFoundError: If the skill is not found
        """
        # Return cached content if available
        if skill_name in self._skill_content_cache:
            logger.debug(f"Returning cached content for skill: {skill_name}")
            return self._skill_content_cache[skill_name]

        raise FileNotFoundError(f"Skill not found: {skill_name}")
