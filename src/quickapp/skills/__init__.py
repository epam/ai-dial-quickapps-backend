from injector import Module

from quickapp.skills.exceptions import SkillFileNotFoundError
from quickapp.skills.frontmatter import parse_frontmatter
from quickapp.skills.skill_metadata import SkillMetadata
from quickapp.skills.dial.dial_skills_module import DialSkillsModule
from quickapp.skills.dial_prompt.dial_prompt_skills_module import DialPromptSkillsModule
from quickapp.skills.invocation.skill_invocation_module import SkillInvocationModule
from quickapp.skills.registry.skills_module import SkillsModule
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
# imports ``quickapp.skills`` would deadlock on a partially-initialized ``__init__``.
skills_module: list[Module] = [
    SkillsModule(),
    DialPromptSkillsModule(),
    DialSkillsModule(),
    SkillInvocationModule(),
]

__all__ = [
    "ResolvedSkill",
    "SkillFileNotFoundError",
    "SkillFileReader",
    "SkillMetadata",
    "SkillsProvider",
    "parse_frontmatter",
    "skills_module",
]
