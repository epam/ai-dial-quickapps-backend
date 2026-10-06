from pydantic import BaseModel, Field, model_validator


class SubagentConfig(BaseModel):
    """A subagent type this app may spawn.

    A subagent runs its own orchestrator loop with its own system prompt, model,
    iteration budget, and tool sets, and returns a single result. It inherits the
    app's contexts, skills, hooks, and features. Its tools are narrowed per tool
    set, not per individual tool.
    """

    name: str = Field(description="Identifier the coordinator uses to select this subagent.")
    description: str = Field(
        description="When to use this subagent. Surfaced to the coordinator's LLM for routing."
    )
    system_prompt: str = Field(
        description="The subagent's instructions. Replaces the app system prompt, never appends."
    )
    tool_sets: list[str] | None = Field(
        default=None,
        description=(
            "Names of the app's tool sets this subagent may use. "
            "When unset, the subagent inherits every tool set."
        ),
    )
    deployment_id: str | None = Field(
        default=None,
        description="Deployment for this subagent. When unset, the coordinator's is inherited.",
    )
    max_iterations: int | None = Field(
        default=None,
        gt=0,
        description="Iteration budget for this subagent. When unset, the coordinator's is inherited.",
    )


class SubagentsConfig(BaseModel):
    """Delegation to subagents through the built-in ``task`` tool.

    A subagent is a helper agent the app spawns to carry out one scoped task. It runs
    its own orchestrator loop and returns a single result; its intermediate steps never
    enter the coordinator's conversation. The builder declares each subagent type with
    a fixed prompt and tool allowlist.
    """

    enabled: bool = Field(
        default=False,
        description="Whether to offer the `task` tool, which spawns subagents.",
    )
    types: list[SubagentConfig] = Field(
        default_factory=list,
        description=(
            "Subagent types declared by the builder, each with a fixed system prompt and "
            "tool allowlist. The coordinator selects one by name."
        ),
    )
    timeout_seconds: float | None = Field(
        default=None,
        gt=0,
        description=(
            "Wall-clock budget for one spawn. Narrows the admin ceiling set by "
            "`SUBAGENT_TIMEOUT_SECONDS` but never extends it."
        ),
    )

    @model_validator(mode="after")
    def _names_are_unique(self) -> "SubagentsConfig":
        names = [subagent.name for subagent in self.types]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ValueError(f"Subagent names must be unique; duplicated: {duplicates}")
        return self
