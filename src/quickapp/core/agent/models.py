from pydantic import BaseModel, ConfigDict

from quickapp.config.tools.base import OpenAiToolConfigDict

TOOL_EXECUTION_HISTORY: str = "tool_execution_history"
STATE_KEY_ORCHESTRATOR: str = "orchestrator_state"
STATE_KEY_CONTEXT_USAGE: str = "context_usage"


class ContextUsage(BaseModel):
    """Token counts of the orchestrator's last LLM call in a turn (context window usage)."""

    model_config = ConfigDict(frozen=True)

    prompt_tokens: int
    completion_tokens: int


__all__ = [
    "TOOL_EXECUTION_HISTORY",
    "STATE_KEY_ORCHESTRATOR",
    "STATE_KEY_CONTEXT_USAGE",
    "ContextUsage",
    "OpenAiToolConfigDict",
]
