import logging
import os
import re
from pathlib import Path
from typing import List, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class SkillMetadata:
    """Metadata extracted from a skill file's YAML frontmatter."""
    name: str
    description: str
    file_name: str
    tags: Optional[List[str]] = None
    version: Optional[str] = None


class AgentSkillsProvider:
    """
    Provider for agent skills. Loads skills from `config/predefined/skills/`,
    parses YAML frontmatter, provides XML metadata, and reads skill file contents.
    """

    def __init__(self) -> None:
        self._xml_metadata: str = ""
        self._skills_dir: Optional[Path] = None
        self._load_skills()

    def _get_skills_directory(self) -> Path:
        """Get the skills directory path."""
        if self._skills_dir is not None:
            return self._skills_dir

        predefined_base = os.environ.get("PREDEFINED_BASE_PATH")
        if predefined_base:
            self._skills_dir = Path(predefined_base) / "skills"
        else:
            # Calculate from common folder: src/quickapp/common -> config/predefined/skills
            project_root = Path(__file__).parents[3]
            self._skills_dir = project_root / "config" / "predefined" / "skills"

        return self._skills_dir

    def _parse_frontmatter(self, content: str, file_name: str) -> Optional[SkillMetadata]:
        """
        Parse YAML frontmatter from markdown content.
        Expected format:
        ---
        name: Skill Name
        description: Brief description
        tags: [tag1, tag2]
        version: 1.0.0
        ---
        """
        # Match YAML frontmatter between --- delimiters
        frontmatter_pattern = r'^---\s*\n(.*?)\n---\s*\n'
        match = re.match(frontmatter_pattern, content, re.DOTALL)

        if not match:
            logger.warning(f"No YAML frontmatter found in {file_name}")
            return None

        frontmatter = match.group(1)

        # Simple YAML parsing (without external dependency)
        metadata = {}
        for line in frontmatter.split('\n'):
            line = line.strip()
            if ':' in line:
                key, value = line.split(':', 1)
                key = key.strip()
                value = value.strip()

                # Handle list format [item1, item2]
                if value.startswith('[') and value.endswith(']'):
                    value = [v.strip() for v in value[1:-1].split(',')]

                metadata[key] = value

        # Extract required fields
        name = metadata.get('name')
        description = metadata.get('description')

        if not name or not description:
            logger.warning(f"Missing required fields (name/description) in {file_name}")
            return None

        return SkillMetadata(
            name=name,
            description=description,
            file_name=file_name,
            tags=metadata.get('tags'),
            version=metadata.get('version')
        )

    def _generate_xml(self, skills: List[SkillMetadata]) -> str:
        """Generate XML format for available skills."""
        if not skills:
            return ""

        xml_parts = ["<available_skills>"]

        for skill in skills:
            xml_parts.append("  <skill>")
            xml_parts.append(f"    <name>{self._escape_xml(skill.name)}</name>")
            xml_parts.append(f"    <description>{self._escape_xml(skill.description)}</description>")
            xml_parts.append(f"    <file_name>{self._escape_xml(skill.file_name)}</file_name>")
            xml_parts.append("  </skill>")

        xml_parts.append("</available_skills>")

        return "\n".join(xml_parts)

    def _escape_xml(self, text: str) -> str:
        """Escape XML special characters."""
        return (text
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;")
                .replace("'", "&apos;"))

    def _load_skills(self) -> None:
        """Load all skill files and generate XML metadata."""
        skills_dir = self._get_skills_directory()

        if not skills_dir.exists() or not skills_dir.is_dir():
            logger.debug(f"No skills directory found at `{skills_dir}`")
            self._xml_metadata = ""
            return

        md_files: List[Path] = sorted(skills_dir.glob("*.md"))
        if not md_files:
            logger.debug(f"No `.md` files found in `{skills_dir}`")
            self._xml_metadata = ""
            return

        skills: List[SkillMetadata] = []
        for md in md_files:
            try:
                logger.debug(f"Loading skill file `{md}`")
                content = md.read_text(encoding="utf-8")
                metadata = self._parse_frontmatter(content, md.name)
                if metadata:
                    skills.append(metadata)
            except Exception as exc:
                logger.error(f"Failed to parse skill file `{md}`: {exc}")

        self._xml_metadata = self._generate_xml(skills)
        logger.info(f"Loaded {len(skills)} skill(s)")

    def get_skills_xml(self) -> str:
        """
        Public method: Returns XML metadata for all available skills.
        Use this to inject skill metadata into the agent's system prompt.
        """
        return self._xml_metadata

    def get_skill_content(self, file_name: str) -> str:
        """
        Public method: Read and return the full content of a specific skill file.

        Args:
            file_name: The filename of the skill (e.g., 'builtin_file_transfer.md')

        Returns:
            The full content of the skill file

        Raises:
            ValueError: If the filename is invalid or contains path traversal attempts
            FileNotFoundError: If the skill file or skills directory doesn't exist
        """
        # Validate filename to prevent path traversal attacks
        if ".." in file_name or "/" in file_name or "\\" in file_name:
            raise ValueError(f"Invalid filename: {file_name}")

        skills_dir = self._get_skills_directory()

        if not skills_dir.exists() or not skills_dir.is_dir():
            raise FileNotFoundError(f"Skills directory not found: {skills_dir}")

        skill_file = skills_dir / file_name

        if not skill_file.exists():
            raise FileNotFoundError(f"Skill file not found: {file_name}")

        # Ensure the resolved path is within the skills directory (security check)
        try:
            resolved_skill_file = skill_file.resolve()
            resolved_skills_dir = skills_dir.resolve()
            if not str(resolved_skill_file).startswith(str(resolved_skills_dir)):
                raise ValueError(f"Access denied: {file_name}")
        except Exception as e:
            logger.error(f"Error resolving path for {file_name}: {e}")
            raise ValueError(f"Invalid file path: {file_name}")

        try:
            content = skill_file.read_text(encoding="utf-8")
            logger.info(f"Successfully read skill file: {file_name}")
            return content
        except Exception as e:
            logger.error(f"Error reading skill file {file_name}: {e}")
            raise
