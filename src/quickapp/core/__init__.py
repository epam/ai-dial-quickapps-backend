from injector import Module

from quickapp.agent.agent_module import AgentModule
from quickapp.application import AppModule

# The app's central DI modules. ``app_factory`` splices this array into its module list
# instead of registering each entry individually. (Physically relocating the ``agent/``
# and ``application/`` source trees into ``core/`` is a follow-up; for now this aggregates
# the existing modules from their current packages.)
core_module: list[Module] = [
    AppModule(),
    AgentModule(),
]
