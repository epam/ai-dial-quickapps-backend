from pydantic import BaseModel


class SkillMetadata(BaseModel):
    """Metadata extracted from a skill file's YAML frontmatter."""

    name: str
    description: str
    license: str | None = None
    compatibility: str | None = None
    metadata: dict | None = None
    allowed_tools: list[str] | None = None
