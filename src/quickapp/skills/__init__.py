from quickapp.skills.exceptions import SkillFileNotFoundError
from quickapp.skills.frontmatter import parse_frontmatter
from quickapp.skills.skill_metadata import SkillMetadata
from quickapp.skills.skill_resolver import DialSkillResourceResolver, SkillResolution
from quickapp.skills.skills_provider import ResolvedSkill, SkillFileReader, SkillsProvider

# The contract every skill source implements. Importing it pulls in nothing but these
# leaf modules — no sub-package, no DI wiring — so this barrel is safe to import from
# anywhere, ``quickapp.skills`` sub-packages included. The module array that does reach
# into the sub-packages lives in ``skills_di.py`` for exactly that reason.

__all__ = [
    "DialSkillResourceResolver",
    "ResolvedSkill",
    "SkillFileNotFoundError",
    "SkillFileReader",
    "SkillMetadata",
    "SkillResolution",
    "SkillsProvider",
    "parse_frontmatter",
]
