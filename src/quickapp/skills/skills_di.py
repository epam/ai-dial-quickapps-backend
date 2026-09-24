from injector import Module

from quickapp.skills.dial_prompt.dial_prompt_skills_module import DialPromptSkillsModule
from quickapp.skills.dial_resource.dial_skills_module import DialSkillsModule
from quickapp.skills.invocation.skill_invocation_module import SkillInvocationModule
from quickapp.skills.registry.skills_module import SkillsModule

# ``app_factory`` splices this array in, so a new skill source joins by appending here.
# Preview-gated entries stay in the list — ``AppFactory.build_di_modules`` filters
# ``is_preview_module`` over the flattened result.
#
# Deliberately not in ``skills/__init__.py``: assembling the array imports every
# sub-package, which would give the contract package a dependency on its own sources and
# make ``from quickapp.skills import ...`` a circular import for any of them.
skills_module: list[Module] = [
    SkillsModule(),
    DialPromptSkillsModule(),
    DialSkillsModule(),
    SkillInvocationModule(),
]
