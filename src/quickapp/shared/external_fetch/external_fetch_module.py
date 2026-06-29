from fastapi_injector import request_scope
from injector import Binder, Module, singleton

from quickapp.shared.external_fetch._external_fetch_settings import ExternalFetchSettings
from quickapp.shared.external_fetch.external_url_fetch_policy_resolver import (
    ExternalUrlFetchPolicyResolver,
)
from quickapp.shared.external_fetch.external_url_fetcher import ExternalUrlFetcher


class ExternalFetchModule(Module):
    """DI bindings for the external-URL fetch egress envelope.

    Owns the trio previously bound inline in ``AppModule``: the admin-level
    ``ExternalFetchSettings`` singleton plus the request-scoped policy resolver
    and fetcher.
    """

    def configure(self, binder: Binder) -> None:
        binder.bind(ExternalFetchSettings, to=ExternalFetchSettings, scope=singleton)
        binder.bind(
            ExternalUrlFetchPolicyResolver,
            to=ExternalUrlFetchPolicyResolver,
            scope=request_scope,
        )
        binder.bind(ExternalUrlFetcher, to=ExternalUrlFetcher, scope=request_scope)
