import re

import yaml

from quickapp.skills.exceptions import SkillValidationError
from quickapp.skills.skill_metadata import SkillMetadata

_FRONTMATTER_RE = re.compile(
    r"\A﻿?[ \t\r\n]*---[ \t\r]*\n(.*?)\n---[ \t\r]*(?:\n|\Z)",
    re.DOTALL,
)
_QUOTABLE_LINE_RE = re.compile(r"^([A-Za-z_][\w-]*):[ \t]+(.+\S)[ \t]*$")


def parse_frontmatter(content: str, source_id: str) -> SkillMetadata:
    """Parse YAML frontmatter delimited by ``---`` and return its ``SkillMetadata``.

    Only structural problems reject a skill; the spec's length and naming
    recommendations aren't checked.

    Raises:
        SkillValidationError: if the content has no frontmatter, the YAML is
            unparseable even after a quote-retry, the YAML is not a mapping,
            ``allowed-tools`` has an invalid format, or ``name`` /
            ``description`` are missing or empty.

    Args:
        content: The full skill content string.
        source_id: Identifier for error messages (file path or prompt URL).
    """
    match = _FRONTMATTER_RE.match(content)
    if not match:
        raise SkillValidationError(source_id, "No YAML frontmatter found")

    parsed = _parse_yaml(match.group(1), source_id)

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

    return SkillMetadata(
        name=name,
        description=description,
        license=parsed.get("license"),
        compatibility=parsed.get("compatibility"),
        metadata=parsed.get("metadata") or None,
        allowed_tools=parsed.get("allowed_tools"),
    )


def _parse_yaml(text: str, source_id: str) -> object:
    """Parse YAML, retrying once with a quote-repair if the first attempt fails.

    Raises ``SkillValidationError`` if the YAML can't be parsed even after the repair.
    """
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as original_exc:
        repaired = _quote_unquoted_colons(text)
        if repaired != text:
            try:
                return yaml.safe_load(repaired)
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
