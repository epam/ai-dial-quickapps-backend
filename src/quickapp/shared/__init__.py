from injector import Module

from quickapp.shared.config_resolvers.config_resolvers_module import ConfigResolversModule
from quickapp.shared.dial_files.dial_files_module import DialFilesModule
from quickapp.shared.external_fetch.external_fetch_module import ExternalFetchModule

# Cross-cutting utility DI modules. ``app_factory`` splices this array into its module
# list, so future utility modules join by appending here rather than being registered
# individually.
shared_module: list[Module] = [
    ConfigResolversModule(),
    ExternalFetchModule(),
    DialFilesModule(),
]
