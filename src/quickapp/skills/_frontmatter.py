import re

import yaml

from quickapp.skills._exceptions import SkillValidationError
from quickapp.skills._skill_metadata import SkillMetadata

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_SKILL_NAME_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")


def parse_frontmatter(content: str, source_id: str) -> SkillMetadata:
    """Parse YAML frontmatter delimited by ``---`` and return validated SkillMetadata.

    Raises:
        SkillValidationError: If the content is missing frontmatter or
            fails any validation rule.

    Args:
        content: The full skill content string.
        source_id: Identifier for error messages (file path or prompt URL).
    """
    match = _FRONTMATTER_RE.match(content)

    if not match:
        raise SkillValidationError(source_id, "No YAML frontmatter found")

    try:
        parsed = yaml.safe_load(match.group(1))
    except yaml.YAMLError as exc:
        raise SkillValidationError(source_id, f"Failed to parse YAML frontmatter: {exc}")

    if not isinstance(parsed, dict):
        raise SkillValidationError(source_id, "YAML frontmatter is not a dictionary")

    # Normalize 'allowed-tools' hyphenated key to 'allowed_tools'
    if "allowed-tools" in parsed:
        allowed_tools_value = parsed.pop("allowed-tools")
        if isinstance(allowed_tools_value, str):
            parsed["allowed_tools"] = allowed_tools_value.split()
        elif isinstance(allowed_tools_value, list):
            parsed["allowed_tools"] = allowed_tools_value
        else:
            raise SkillValidationError(source_id, "Invalid allowed-tools format")

    name = parsed.get("name")
    description = parsed.get("description")

    if not name or not description:
        raise SkillValidationError(source_id, "Missing required fields (name/description)")

    if len(name) > 64:
        raise SkillValidationError(source_id, f"Skill name exceeds 64 characters: {name}")

    if "--" in name or not _SKILL_NAME_RE.match(name):
        raise SkillValidationError(
            source_id,
            f"Invalid skill name format: {name}"
            " (must be lowercase letters, numbers, hyphens;"
            " no leading/trailing or consecutive hyphens)",
        )

    if len(description) > 1024:
        raise SkillValidationError(source_id, "Description exceeds 1024 characters")

    compatibility = parsed.get("compatibility")
    if compatibility is not None and len(compatibility) > 500:
        raise SkillValidationError(source_id, "Compatibility exceeds 500 characters")

    return SkillMetadata(
        name=name,
        description=description,
        license=parsed.get("license"),
        compatibility=compatibility,
        metadata=parsed.get("metadata") or None,
        allowed_tools=parsed.get("allowed_tools"),
    )
