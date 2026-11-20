import logging
from collections.abc import Iterable
from typing import ClassVar

from injector import inject

from quickapp.common import ForwardedHeaders
from quickapp.common.dial_origin import is_dial_origin
from quickapp.common.dial_settings import DialSettings
from quickapp.common.localized_string import resolve_localized
from quickapp.config.toolsets.deployment import DeploymentToolSet
from quickapp.config.toolsets.dial_app import DialAppToolSet
from quickapp.config.toolsets.dial_mcp import DialMCPToolSet
from quickapp.config.toolsets.mcp import MCPToolSet
from quickapp.config.toolsets.rest_api import RestApiToolSet
from quickapp.shared.forwarded_headers._forwarded_headers_settings import ForwardedHeadersSettings

logger = logging.getLogger(__name__)

ForwardingToolSet = (
    RestApiToolSet | MCPToolSet | DialMCPToolSet | DeploymentToolSet | DialAppToolSet
)


@inject
class ForwardedHeadersPolicy:
    """Decides which of the request's X-* headers each toolset receives.

    A toolset that sets ``forwarded_headers`` gets exactly those headers. Otherwise a toolset
    inside the DIAL contour gets every X-* header and an external one (REST API, MCP on a
    non-DIAL origin) gets none, unless the admin migration switch is on.
    """

    _reported_drops: ClassVar[set[tuple[str, frozenset[str]]]] = set()

    def __init__(
        self,
        forwarded_headers: ForwardedHeaders,
        settings: ForwardedHeadersSettings,
        dial_settings: DialSettings,
    ) -> None:
        self.__headers: ForwardedHeaders = forwarded_headers
        self.__settings = settings
        self.__dial_settings = dial_settings

    def all(self) -> ForwardedHeaders:
        """Every X-* header of the request, for consumers that are not toolsets."""
        return self.__headers

    def for_toolset(self, toolset: ForwardingToolSet) -> ForwardedHeaders:
        if toolset.forwarded_headers is not None:
            return self.__select(toolset.forwarded_headers)
        if not self.__is_external(toolset) or self.__settings.forward_all_to_external:
            return self.__headers
        self.__report_dropped(toolset)
        return None

    def __is_external(self, toolset: ForwardingToolSet) -> bool:
        if isinstance(toolset, RestApiToolSet):
            return True
        if isinstance(toolset, MCPToolSet):
            return not is_dial_origin(toolset.mcp_server_info.url, self.__dial_settings.url)
        return False

    def __select(self, names: Iterable[str]) -> ForwardedHeaders:
        if not self.__headers:
            return None
        original_names = {name.lower(): name for name in self.__headers}
        selected = {
            original_names[name]: self.__headers[original_names[name]]
            for name in names
            if name in original_names
        }
        return selected or None

    def __report_dropped(self, toolset: ForwardingToolSet) -> None:
        if not self.__headers:
            return
        toolset_name = resolve_localized(toolset.name)
        dropped = frozenset(name.lower() for name in self.__headers)
        key = (toolset_name, dropped)
        if key in self._reported_drops:
            return
        self._reported_drops.add(key)
        logger.info(
            "Toolset '%s' is external and sets no forwarded_headers, so these X-* request "
            "headers are not sent to it: %s. List them in the toolset's forwarded_headers to "
            "forward them.",
            toolset_name,
            ", ".join(sorted(dropped)),
        )
