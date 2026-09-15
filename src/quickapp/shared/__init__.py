from injector import Module

from quickapp.shared.config_resolvers.config_resolvers_module import ConfigResolversModule
from quickapp.shared.external_fetch.external_fetch_module import ExternalFetchModule
from quickapp.shared.home_path.home_path_module import HomePathModule

# Cross-cutting utility DI modules. ``app_factory`` splices this array into its module
# list, so future utility modules join by appending here rather than being registered
# individually.
shared_module: list[Module] = [
    ConfigResolversModule(),
    ExternalFetchModule(),
    HomePathModule(),
]
