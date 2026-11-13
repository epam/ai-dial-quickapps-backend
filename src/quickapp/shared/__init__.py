from injector import Module

from quickapp.shared.config_resolvers.config_resolvers_module import ConfigResolversModule
from quickapp.shared.deployment_client.deployment_client_module import DeploymentClientModule
from quickapp.shared.external_fetch.external_fetch_module import ExternalFetchModule
from quickapp.shared.home_path.home_path_module import HomePathModule
from quickapp.shared.project.project_module import ProjectModule
from quickapp.shared.user_access.user_access_module import UserAccessModule

# Cross-cutting utility DI modules. ``app_factory`` splices this array into its module
# list, so future utility modules join by appending here rather than being registered
# individually. ``ProjectModule`` goes first: its prompt section must directly follow the
# app's own system prompt (``core_module``), ahead of every other prompt part.
shared_module: list[Module] = [
    ProjectModule(),
    ConfigResolversModule(),
    DeploymentClientModule(),
    ExternalFetchModule(),
    HomePathModule(),
    UserAccessModule(),
]
