from pydantic import BaseModel, Field


class SubagentsConfig(BaseModel):
    """Configuration for the built-in ``general-purpose`` subagent.

    A subagent is a helper agent the app spawns to carry out one scoped task. It runs
    its own orchestrator loop and returns a single result; its intermediate steps never
    enter the coordinator's conversation.

    There is exactly one subagent type. Which tools a given spawn may use is not decided
    here — the coordinator names them per call through the ``task`` tool's ``tool_sets``
    argument, so a spoke's tool surface fits the task rather than the whole app.
    """

    enabled: bool = Field(
        default=False,
        description="Whether to offer the `task` tool, which spawns a general-purpose subagent.",
    )
    system_prompt: str | None = Field(
        default=None,
        description=(
            "The subagent's instructions. Replaces the built-in general-purpose prompt, "
            "never appends to it. When unset, the built-in prompt is used."
        ),
    )
    deployment_id: str | None = Field(
        default=None,
        description="Deployment subagents run on. When unset, the app's orchestrator model is used.",
    )
    max_iterations: int | None = Field(
        default=None,
        gt=0,
        description="Iteration budget for one spawn. When unset, the app's budget is used.",
    )
    timeout_seconds: float | None = Field(
        default=None,
        gt=0,
        description=(
            "Wall-clock budget for one spawn. Narrows the admin ceiling set by "
            "`SUBAGENT_TIMEOUT_SECONDS` but never extends it."
        ),
    )
