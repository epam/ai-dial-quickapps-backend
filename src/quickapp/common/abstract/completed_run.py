from typing import Protocol

from quickapp.common.deployment_usage import DeploymentUsage


class CompletedRun(Protocol):
    """What a caller of ``BaseCompletionRunner`` can read from a finished run."""

    @property
    def usage_statistics(self) -> list[DeploymentUsage]: ...
