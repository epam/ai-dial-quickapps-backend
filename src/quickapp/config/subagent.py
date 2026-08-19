from pydantic import BaseModel, Field


class SubagentConfig(BaseModel):
    """A subagent type declared by the app builder.

    A spoke inherits the coordinator's ``contexts`` / ``skills`` / ``hooks`` /
    ``features`` wholesale (see ``compile_subagent_manifest``), so there is no
    field for them here. Per-subagent *narrowing* of those, and a tool-level
    (rather than toolset-level) allowlist, are intentionally out of scope — see
    ``docs/designs/anonymous_subagents.md``.
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
