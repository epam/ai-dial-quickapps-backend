from xml.sax.saxutils import escape as _stdlib_escape

from quickapp.skills.agent_skills_provider import SkillMetadata

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
