from quickapp.config.tools.base import OpenAiToolConfigDict

TOOL_EXECUTION_HISTORY: str = "tool_execution_history"
# Names of deferred tools discovered via tool_search, carried across turns so their schemas
# stay in `tools` on later requests.
DISCOVERED_TOOLS: str = "discovered_tools"
STATE_KEY_ORCHESTRATOR: str = "orchestrator_state"

__all__ = [
    "TOOL_EXECUTION_HISTORY",
    "DISCOVERED_TOOLS",
    "STATE_KEY_ORCHESTRATOR",
    "OpenAiToolConfigDict",
]
