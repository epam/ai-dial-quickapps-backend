from injector import Module

from quickapp.core.agent.agent_module import AgentModule
from quickapp.core.application import AppModule

core_module: list[Module] = [
    AppModule(),
    AgentModule(),
]

__all__ = ["core_module"]
