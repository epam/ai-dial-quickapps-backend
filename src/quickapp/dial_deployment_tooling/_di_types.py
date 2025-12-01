from typing import Annotated

from aidial_client.types.deployment import DeploymentBase

from quickapp.common.cache import CacheService
from quickapp.config.tools.deployment import DialDeploymentTool

APPLICATIONS_AS_TOOLS = Annotated[list[DeploymentBase], "APPLICATIONS_AS_TOOLS"]


class DialDeploymentToolCacheService(CacheService[DialDeploymentTool]):
    pass
