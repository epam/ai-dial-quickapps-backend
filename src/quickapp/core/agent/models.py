from quickapp.config.tools.base import OpenAiToolConfigDict

TOOL_EXECUTION_HISTORY: str = "tool_execution_history"
STATE_KEY_ORCHESTRATOR: str = "orchestrator_state"
# State key holding the name of the tool whose form_schema was last propagated to the choice.
STATE_KEY_FORM_SCHEMA_SOURCE_TOOL: str = "form_schema_source_tool"

__all__ = [
    "TOOL_EXECUTION_HISTORY",
    "STATE_KEY_ORCHESTRATOR",
    "STATE_KEY_FORM_SCHEMA_SOURCE_TOOL",
    "OpenAiToolConfigDict",
]
