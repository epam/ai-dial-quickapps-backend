from pydantic import BaseModel, Field, model_validator

# The built-in subagent's `subagent_type`. Declared types may not reuse it.
GENERAL_PURPOSE_SUBAGENT_NAME = "general-purpose"


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


class GeneralPurposeSubagentConfig(BaseModel):
    """Tuning for the built-in ``general-purpose`` subagent.

    Unlike a declared type, its tool sets are not decided here: the coordinator names
    them per call through the ``task`` tool's ``tool_sets`` argument, so a spoke's tool
    surface fits the task at hand rather than the whole app.
    """

    system_prompt: str | None = Field(
        default=None,
        description=(
            "The subagent's instructions. Replaces the built-in general-purpose prompt, "
            "never appends to it. When unset, the built-in prompt is used."
        ),
    )
    deployment_id: str | None = Field(
        default=None,
        description="Deployment for this subagent. When unset, the coordinator's is inherited.",
    )
    max_iterations: int | None = Field(
        default=None,
        gt=0,
        description="Iteration budget for one spawn. When unset, the coordinator's is inherited.",
    )


class SubagentsConfig(BaseModel):
    """Delegation to subagents through the built-in ``task`` tool.

    A subagent is a helper agent the app spawns to carry out one scoped task. It runs
    its own orchestrator loop and returns a single result; its intermediate steps never
    enter the coordinator's conversation.

    Two kinds are offered side by side: the built-in ``general-purpose`` subagent, whose
    tools the coordinator picks per call, and the ``types`` the builder declares, each
    with a fixed prompt and tool allowlist.
    """

    enabled: bool = Field(
        default=False,
        description="Whether to offer the `task` tool, which spawns subagents.",
    )
    general_purpose: GeneralPurposeSubagentConfig | None = Field(
        default_factory=GeneralPurposeSubagentConfig,
        description=(
            f"The built-in `{GENERAL_PURPOSE_SUBAGENT_NAME}` subagent: the coordinator names "
            "the tool sets it may use on every call. Set to null to offer only the "
            "declared `types`."
        ),
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
        if self.general_purpose is not None:
            names.append(GENERAL_PURPOSE_SUBAGENT_NAME)
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ValueError(f"Subagent names must be unique; duplicated: {duplicates}")
        return self
