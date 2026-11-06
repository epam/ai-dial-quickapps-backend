from pydantic import BaseModel, Field

from quickapp.common.deployment_usage import ModelUsage


class RoutingResult(BaseModel):
    names: list[str] = Field(default_factory=list)
    usage: ModelUsage | None = None

    def with_usage(self, usage: ModelUsage | None) -> "RoutingResult":
        return RoutingResult(names=self.names, usage=usage)
