import logging

from injector import Binder, Module, ProviderOf, multiprovider, singleton

from quickapp.common.app_lifespan_participant import AppLifespanParticipant
from quickapp.common.base_initializer import StartupInitializer
from quickapp.common.preview import preview_module

from ._mcp_endpoint_service import _McpEndpointService
from ._mcp_route_initializer import _McpRouteInitializer

logger = logging.getLogger(__name__)


@preview_module
class McpEndpointModule(Module):
    def configure(self, binder: Binder) -> None:
        binder.bind(_McpEndpointService, to=_McpEndpointService, scope=singleton)

    @multiprovider
    def _provide_initializers(
        self, initializer_provider: ProviderOf[_McpRouteInitializer]
    ) -> list[StartupInitializer]:
        return [initializer_provider.get()]

    @multiprovider
    def _provide_lifespan_participants(
        self, service: _McpEndpointService
    ) -> list[AppLifespanParticipant]:
        return [service]
