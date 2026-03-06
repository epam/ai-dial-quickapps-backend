from typing import Annotated, Literal

from pydantic import BaseModel, Field

from quickapp.common.base_config import DialResourceConfigField


class DialDeploymentSimpleTool(BaseModel):
    deployment_id: Annotated[str, DialResourceConfigField(description="The id of the deployment")]
    enabled: bool = Field(default=True, description="Whether the tool is enabled.")
    type: Literal["dial-deployment-simple"] = Field(default="dial-deployment-simple")
