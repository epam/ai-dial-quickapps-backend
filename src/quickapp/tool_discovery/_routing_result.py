from pydantic import BaseModel, ConfigDict, Field

from quickapp.common.deployment_usage import ModelUsage


class RoutingResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    names: list[str] = Field(default_factory=list)
    usage: ModelUsage | None = None
    # User-facing notes about the routing call(s), e.g. a rejected request. Carried on the result
    # (not on the shared agent) so concurrent searches never see each other's warnings.
    warnings: list[str] = Field(default_factory=list)

    @staticmethod
    def combine(names: list[str], *results: "RoutingResult") -> "RoutingResult":
        """Build the result of a multi-call search: `names` plus the usage and warnings of all calls.

        All calls are made against the same model. Parallel calls that fail identically produce
        the same warning, so warnings are de-duplicated.
        """
        usages = [r.usage for r in results if r.usage is not None]
        usage = (
            ModelUsage(
                model=usages[0].model,
                prompt_tokens=sum(u.prompt_tokens for u in usages),
                completion_tokens=sum(u.completion_tokens for u in usages),
            )
            if usages
            else None
        )
        return RoutingResult(
            names=names,
            usage=usage,
            warnings=list(dict.fromkeys(w for r in results for w in r.warnings)),
        )
