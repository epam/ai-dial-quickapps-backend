from injector import Module

from quickapp.skills.dial_prompt.dial_prompt_skills_module import DialPromptSkillsModule
from quickapp.skills.dial_resource.dial_skills_module import DialSkillsModule
from quickapp.skills.invocation.skill_invocation_module import SkillInvocationModule
from quickapp.skills.registry.skills_module import SkillsModule

# The skill DI modules: the never-gated registry plus one module per source.
# ``app_factory`` splices this array into its module list, so a new source joins by
# appending here rather than being registered individually. Preview-gated entries stay
# in the array — ``AppFactory.build_di_modules`` filters ``is_preview_module`` over the
# flattened list. Order is preserved from the original registration: the registry first,
# then the sources.
#
# This lives beside ``skills/__init__.py`` rather than inside it on purpose. Assembling
# the array imports every sub-package, and a sub-package importing ``quickapp.skills``
# while that ran would hit a circular import against a partially-initialized module.
# Keeping the assembly out of ``__init__`` means the barrel never reaches into a
# sub-package, so the contract package has no dependency on its sources at all.
skills_module: list[Module] = [
    SkillsModule(),
    DialPromptSkillsModule(),
    DialSkillsModule(),
    SkillInvocationModule(),
]
