from injector import Module

# Import order below is deliberate, and isort leaves it alone (extend_skip_glob covers
# __init__.py). The sub-packages come FIRST so that a sub-package importing this barrel
# fails every time: while these four lines run, ``quickapp.skills`` is in sys.modules but
# carries no attributes yet, so ``from quickapp.skills import ResolvedSkill`` raises
# ImportError. Bind the contract names first and that same mistake silently succeeds for
# whichever names happen to be bound already — a rule that only half-enforces.
from quickapp.skills.dial.dial_skills_module import DialSkillsModule
from quickapp.skills.dial_prompt.dial_prompt_skills_module import DialPromptSkillsModule
from quickapp.skills.invocation.skill_invocation_module import SkillInvocationModule
from quickapp.skills.registry.skills_module import SkillsModule
from quickapp.skills.exceptions import SkillFileNotFoundError
from quickapp.skills.frontmatter import parse_frontmatter
from quickapp.skills.skill_metadata import SkillMetadata
from quickapp.skills.skill_resolver import DialSkillResourceResolver, SkillResolution
from quickapp.skills.skills_provider import ResolvedSkill, SkillFileReader, SkillsProvider

# The skill DI modules: the never-gated registry plus one module per source.
# ``app_factory`` splices this array into its module list, so a new source joins by
# appending here rather than being registered individually. Preview-gated entries stay
# in the array — ``AppFactory.build_di_modules`` filters ``is_preview_module`` over the
# flattened list.
#
# Import rule for everything under ``quickapp.skills``: import the concrete contract
# module (``from quickapp.skills.skills_provider import ResolvedSkill``), never this
# barrel. Building the array here imports the sub-packages, so a sub-package that
# imports ``quickapp.skills`` hits a circular import against a partially-initialized
# module.
skills_module: list[Module] = [
    SkillsModule(),
    DialPromptSkillsModule(),
    DialSkillsModule(),
    SkillInvocationModule(),
]

__all__ = [
    "DialSkillResourceResolver",
    "ResolvedSkill",
    "SkillFileNotFoundError",
    "SkillFileReader",
    "SkillMetadata",
    "SkillResolution",
    "SkillsProvider",
    "parse_frontmatter",
    "skills_module",
]
