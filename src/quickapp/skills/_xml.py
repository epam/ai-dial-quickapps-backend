from xml.sax.saxutils import escape as _stdlib_escape

from quickapp.skills._skill import SkillFileEntry
from quickapp.skills._skill_metadata import SkillMetadata

_QUOTE_ENTITIES = {'"': "&quot;", "'": "&apos;"}


def escape_xml(text: str) -> str:
    """Escape XML special characters including quotes (for use in attributes)."""
    return _stdlib_escape(text, _QUOTE_ENTITIES)


def generate_skills_xml(skills: list[SkillMetadata]) -> str:
    """Generate XML representation of available skills for the system prompt."""
    if not skills:
        return ""

    xml_parts = ["<available_skills>"]

    for skill_metadata in skills:
        xml_parts.append("  <skill>")
        xml_parts.append(f"    <name>{escape_xml(skill_metadata.name)}</name>")
        xml_parts.append(f"    <description>{escape_xml(skill_metadata.description)}</description>")
        if skill_metadata.license:
            xml_parts.append(f"    <license>{escape_xml(skill_metadata.license)}</license>")
        if skill_metadata.compatibility:
            xml_parts.append(
                f"    <compatibility>{escape_xml(skill_metadata.compatibility)}</compatibility>"
            )
        if skill_metadata.allowed_tools:
            allowed_tools = " ".join(skill_metadata.allowed_tools)
            xml_parts.append(f"    <allowed_tools>{escape_xml(allowed_tools)}</allowed_tools>")
        if skill_metadata.metadata:
            xml_parts.append("    <metadata>")
            for key in sorted(skill_metadata.metadata):
                raw_value = skill_metadata.metadata[key]
                value = "" if raw_value is None else str(raw_value)
                xml_parts.append(
                    f'      <entry key="{escape_xml(str(key))}">{escape_xml(value)}</entry>'
                )
            xml_parts.append("    </metadata>")
        xml_parts.append("  </skill>")

    xml_parts.append("</available_skills>")

    return "\n".join(xml_parts)


_INVENTORY_TRUNCATED_LINE = "... (inventory truncated; this skill has more files)"


def generate_skill_files_xml(
    entries: list[SkillFileEntry],
    truncated: bool = False,
    max_bytes: int | None = None,
) -> str:
    """Render a skill's bundled-file inventory.

    Appended to a *manifest* read, never to ``<available_skills>``: the system
    prompt carries every skill on every request, so file trees there would tax
    every request for detail that only matters once the agent has committed to
    a skill.

    Returns an empty string when the skill has no files beyond ``SKILL.md``,
    so a single-document skill reads exactly as it did before.
    """
    if not entries:
        return ""

    # Deliberately unescaped, unlike the metadata block above. The model copies
    # these paths straight back into `read_skill(file_path=...)`, and
    # `escape_xml` is the *attribute* variant - it turns
    # `references/user's-guide.md` into `references/user&apos;s-guide.md`, a name
    # no lookup can resolve. The recovery hint in the reader tool lists them
    # unescaped too, so escaping here also showed the model two spellings of one
    # file. A skill author already controls SKILL.md's body verbatim, so this
    # opens no door that was not already open.
    paths = [entry.path for entry in entries]
    if max_bytes is not None:
        # The manifest is capped on its own, but the block appended to it was
        # not, so a large manifest plus a long inventory could put a single tool
        # result well past the documented ceiling - and `read_skill` is excluded
        # from offload, so nothing downstream would trim it either.
        kept: list[str] = []
        budget = max_bytes
        for path in paths:
            cost = len(path.encode("utf-8")) + 1
            if cost > budget:
                truncated = True
                break
            budget -= cost
            kept.append(path)
        paths = kept
        if not paths:
            return ""

    lines = ["<skill_files>"]
    lines.extend(paths)
    if truncated:
        lines.append(_INVENTORY_TRUNCATED_LINE)
    lines.append("</skill_files>")
    return "\n".join(lines)
