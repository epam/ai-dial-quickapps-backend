from typing import Literal

from pydantic import BaseModel, Field


class DialDeploymentSimpleTool(BaseModel):
    deployment_id: str = Field(description="The id of the deployment")
    enabled: bool = Field(default=True, description="Whether the tool is enabled.")
    type: Literal["dial-deployment-simple"] = Field(default="dial-deployment-simple")
