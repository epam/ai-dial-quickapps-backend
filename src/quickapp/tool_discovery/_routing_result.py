from pydantic import BaseModel, ConfigDict, Field

from quickapp.common.deployment_usage import ModelUsage


class RoutingResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    names: list[str] = Field(default_factory=list)
    usage: ModelUsage | None = None

    @staticmethod
    def total_usage(*results: "RoutingResult") -> ModelUsage | None:
        """Total the usage of several routing calls (all made against the same model)."""
        usages = [r.usage for r in results if r.usage is not None]
        if not usages:
            return None
        return ModelUsage(
            model=usages[0].model,
            prompt_tokens=sum(u.prompt_tokens for u in usages),
            completion_tokens=sum(u.completion_tokens for u in usages),
        )
