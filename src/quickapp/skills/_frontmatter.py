import logging
import re

import yaml

from quickapp.skills.agent_skills_provider import SkillMetadata

logger = logging.getLogger(__name__)

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_SKILL_NAME_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")


def parse_frontmatter(content: str, source_id: str) -> SkillMetadata | None:
    """Parse YAML frontmatter delimited by ``---`` and return validated SkillMetadata.

    Args:
        content: The full skill content string.
        source_id: Identifier for log messages (file path or prompt URL).
    """
    match = _FRONTMATTER_RE.match(content)

    if not match:
        logger.warning(f"No YAML frontmatter found in {source_id}")
        return None

    try:
        parsed = yaml.safe_load(match.group(1))
    except yaml.YAMLError as exc:
        logger.error(f"Failed to parse YAML frontmatter in {source_id}: {exc}")
        return None

    if not isinstance(parsed, dict):
        logger.warning(f"YAML frontmatter is not a dictionary in {source_id}")
        return None

    # Normalize 'allowed-tools' hyphenated key to 'allowed_tools'
    if "allowed-tools" in parsed:
        allowed_tools_value = parsed.pop("allowed-tools")
        if isinstance(allowed_tools_value, str):
            parsed["allowed_tools"] = allowed_tools_value.split()
        elif isinstance(allowed_tools_value, list):
            parsed["allowed_tools"] = allowed_tools_value
        else:
            logger.warning(f"Invalid allowed-tools format in {source_id}")

    name = parsed.get("name")
    description = parsed.get("description")

    if not name or not description:
        logger.warning(f"Missing required fields (name/description) in {source_id}")
        return None

    if len(name) > 64:
        logger.warning(f"Skill name exceeds 64 characters in {source_id}: {name}")
        return None

    if "--" in name or not _SKILL_NAME_RE.match(name):
        logger.warning(
            f"Invalid skill name format in {source_id}: {name}"
            " (must be lowercase letters, numbers, hyphens;"
            " no leading/trailing or consecutive hyphens)"
        )
        return None

    if len(description) > 1024:
        logger.warning(f"Description exceeds 1024 characters in {source_id}")
        return None

    compatibility = parsed.get("compatibility")
    if compatibility is not None and len(compatibility) > 500:
        logger.warning(f"Compatibility exceeds 500 characters in {source_id}, truncating")
        compatibility = compatibility[:500]

    return SkillMetadata(
        name=name,
        description=description,
        license=parsed.get("license"),
        compatibility=compatibility,
        metadata=parsed.get("metadata") or None,
        allowed_tools=parsed.get("allowed_tools"),
    )
