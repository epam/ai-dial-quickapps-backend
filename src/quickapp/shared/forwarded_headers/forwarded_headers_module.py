import logging

from fastapi_injector import request_scope
from injector import Binder, Module

from quickapp.shared.forwarded_headers._forwarded_headers_settings import ForwardedHeadersSettings
from quickapp.shared.forwarded_headers.forwarded_headers_policy import ForwardedHeadersPolicy

logger = logging.getLogger(__name__)


class ForwardedHeadersModule(Module):
    """DI bindings for per-toolset forwarding of X-* request headers."""

    def configure(self, binder: Binder) -> None:
        settings = ForwardedHeadersSettings()
        if settings.forward_all_to_external:
            logger.warning(
                "FORWARD_ALL_X_HEADERS_TO_EXTERNAL_TOOLSETS is deprecated and will be removed. "
                "List the needed headers in `forwarded_headers` of each external toolset instead."
            )
        binder.bind(ForwardedHeadersSettings, to=settings)
        binder.bind(ForwardedHeadersPolicy, to=ForwardedHeadersPolicy, scope=request_scope)
