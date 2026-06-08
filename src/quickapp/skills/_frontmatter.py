import re

import yaml

from quickapp.skills._exceptions import SkillValidationError
from quickapp.skills._skill_metadata import ParsedSkill, SkillMetadata

_FRONTMATTER_RE = re.compile(
    r"\A﻿?[ \t\r\n]*---[ \t\r]*\n(.*?)\n---[ \t\r]*(?:\n|\Z)",
    re.DOTALL,
)
_SKILL_NAME_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")
_QUOTABLE_LINE_RE = re.compile(r"^([A-Za-z_][\w-]*):[ \t]+(.+\S)[ \t]*$")


def parse_frontmatter(content: str, source_id: str) -> ParsedSkill:
    """Parse YAML frontmatter delimited by ``---`` and return a ``ParsedSkill``.

    Follows the Agent Skills client guide's "lenient with diagnostics" model:
    cosmetic issues are recorded as warnings and the skill is still loaded;
    only missing required fields and irrecoverable YAML errors raise.

    Raises:
        SkillValidationError: if the content has no frontmatter, the YAML is
            unparseable even after a quote-retry, the YAML is not a mapping,
            or ``name`` / ``description`` are missing or empty.

    Args:
        content: The full skill content string.
        source_id: Identifier for error messages (file path or prompt URL).
    """
    match = _FRONTMATTER_RE.match(content)
    if not match:
        raise SkillValidationError(source_id, "No YAML frontmatter found")

    warnings: list[str] = []
    parsed, yaml_warning = _parse_yaml(match.group(1), source_id)
    if yaml_warning is not None:
        warnings.append(yaml_warning)

    if not isinstance(parsed, dict):
        raise SkillValidationError(source_id, "YAML frontmatter is not a dictionary")

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
        warnings.append(f"Skill name exceeds 64 characters: {name}")

    if "--" in name or not _SKILL_NAME_RE.match(name):
        warnings.append(
            f"Skill name does not match recommended format: {name}"
            " (lowercase letters, numbers, hyphens; no leading/trailing or consecutive hyphens)"
        )

    if len(description) > 1024:
        warnings.append("Description exceeds 1024 characters")

    compatibility = parsed.get("compatibility")
    if compatibility is not None and len(compatibility) > 500:
        warnings.append("Compatibility exceeds 500 characters")

    metadata = SkillMetadata(
        name=name,
        description=description,
        license=parsed.get("license"),
        compatibility=compatibility,
        metadata=parsed.get("metadata") or None,
        allowed_tools=parsed.get("allowed_tools"),
    )
    return ParsedSkill(metadata=metadata, warnings=warnings)


def _parse_yaml(text: str, source_id: str) -> tuple[object, str | None]:
    """Parse YAML, retrying once with a quote-repair if the first attempt fails.

    Returns ``(parsed, warning_or_none)``. Raises ``SkillValidationError`` if
    the YAML can't be parsed even after the repair.
    """
    try:
        return yaml.safe_load(text), None
    except yaml.YAMLError as original_exc:
        repaired = _quote_unquoted_colons(text)
        if repaired != text:
            try:
                return (
                    yaml.safe_load(repaired),
                    "YAML repaired by quoting value(s) with unescaped colons",
                )
            except yaml.YAMLError:
                pass
        raise SkillValidationError(source_id, f"Failed to parse YAML frontmatter: {original_exc}")


def _quote_unquoted_colons(text: str) -> str:
    """Wrap top-level scalar values containing unquoted colons in double quotes."""
    out_lines: list[str] = []
    changed = False
    for line in text.splitlines():
        match = _QUOTABLE_LINE_RE.match(line)
        if match is None:
            out_lines.append(line)
            continue
        key, value = match.group(1), match.group(2)
        if value[0] in ("'", '"', "|", ">", "[", "{") or ":" not in value:
            out_lines.append(line)
            continue
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        out_lines.append(f'{key}: "{escaped}"')
        changed = True
    return "\n".join(out_lines) if changed else text
