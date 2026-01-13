from pydantic import BaseModel

ORCHESTRATOR = "Orchestrator"


class DeploymentUsage(BaseModel):
    deployment_id: str = ORCHESTRATOR
    deployment_name: str = ORCHESTRATOR
    model_name: str = "-"
    prompt_tokens: int = 0
    completion_tokens: int = 0

    def is_orchestrator(self) -> bool:
        return self.deployment_id == ORCHESTRATOR and self.deployment_name == ORCHESTRATOR

    def to_dict(self):
        return self.model_dump(exclude_none=True)
