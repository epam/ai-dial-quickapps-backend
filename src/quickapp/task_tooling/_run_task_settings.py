from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class RunTaskSettings(BaseSettings):
    """Operator-level bounds on delegated tasks.

    Tasks share the replica's event loop and memory, so without these one decision
    of the delegating agent can fan out into unbounded work of unbounded duration.
    """

    model_config = SettingsConfigDict()

    timeout_seconds: float = Field(
        default=600.0,
        description=(
            "Admin ceiling on how long one task may run. An app's "
            "`features.run_task.timeout_seconds` may shorten it, never extend it."
        ),
        alias="RUN_TASK_TIMEOUT_SECONDS",
        gt=0,
    )
    max_concurrent: int = Field(
        default=4,
        description=(
            "Maximum tasks running at once in this process, across all requests. "
            "Excess tasks wait for a slot, up to the task's time budget."
        ),
        alias="RUN_TASK_MAX_CONCURRENT",
        gt=0,
    )
