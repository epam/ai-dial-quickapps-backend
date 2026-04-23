from typing import Annotated

from aidial_client.types.deployment import DeploymentBase

APPLICATIONS_AS_TOOLS = Annotated[list[DeploymentBase], "APPLICATIONS_AS_TOOLS"]
