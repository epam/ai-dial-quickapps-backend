import asyncio
import logging
from urllib.parse import unquote

import httpx
from injector import inject

from quickapp.config.application import ApplicationConfig
from quickapp.dial_core_services.deployment_names_service import DeploymentNamesCoreService

logger = logging.getLogger(__name__)


def _normalize(deployment_id: str) -> str:
    # Core reports URL-quoted ids (``applications/<bucket>/my%20app``); manifests may use either form.
    return unquote(deployment_id).strip("/")


@inject
class ToolAccessFilter:
    """Request-scoped check of configured tools against what DIAL Core lets the user call.

    Inert (everything is accessible) unless ``features.tool_access_filter.enabled`` is set.
    Queries DIAL Core lazily, once per request (no cross-request cache). Fails open: when DIAL
    Core cannot be queried, every tool is considered accessible, because DIAL Core still
    enforces access at call time.
    """

    def __init__(
        self,
        app_config: ApplicationConfig,
        deployment_names_service: DeploymentNamesCoreService,
    ):
        tool_access_filter = app_config.features.tool_access_filter if app_config.features else None
        self.__enabled: bool = tool_access_filter is not None and tool_access_filter.enabled
        self.__deployment_names_service: DeploymentNamesCoreService = deployment_names_service
        self.__task: asyncio.Task[frozenset[str] | None] | None = None

    async def is_accessible(self, deployment_id: str) -> bool:
        if not self.__enabled:
            return True
        if self.__task is None:
            self.__task = asyncio.create_task(self.__resolve())
        accessible_ids = await self.__task
        return accessible_ids is None or _normalize(deployment_id) in accessible_ids

    async def __resolve(self) -> frozenset[str] | None:
        try:
            names = await self.__deployment_names_service.list_names()
        except (httpx.HTTPError, ValueError) as e:
            logger.warning(
                "Could not load accessible deployments (%s); offering all configured tools",
                type(e).__name__,
            )
            return None
        return frozenset(_normalize(name) for name in names)
