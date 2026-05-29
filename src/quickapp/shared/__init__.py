from injector import Module

from quickapp.shared.external_fetch.external_fetch_module import ExternalFetchModule

# Cross-cutting utility DI modules. ``app_factory`` splices this array into its module
# list, so future utility modules join by appending here rather than being registered
# individually.
shared_module: list[Module] = [
    ExternalFetchModule(),
]
