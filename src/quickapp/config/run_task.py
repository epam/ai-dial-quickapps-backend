from pydantic import BaseModel, Field


class RunTaskConfig(BaseModel):
    """Per-app config for the built-in ``internal_run_task`` tool.

    The tool runs a self-contained task in an isolated child run and returns only its
    final answer. The child uses this app's deployment and inherits its contexts,
    skills and ``on_request_start`` hooks; the delegating agent picks its tools per call.
    """

    enabled: bool = Field(
        default=False,
        description="Whether to expose the internal_run_task tool to the LLM.",
    )
    max_iterations: int | None = Field(
        default=None,
        gt=0,
        description=(
            "Iteration budget for one task. When unset, the app's "
            "`orchestrator.max_iterations` applies."
        ),
    )
    timeout_seconds: float | None = Field(
        default=None,
        gt=0,
        description=(
            "Wall-clock budget for one task. May shorten the `RUN_TASK_TIMEOUT_SECONDS` "
            "ceiling, never extend it."
        ),
    )
