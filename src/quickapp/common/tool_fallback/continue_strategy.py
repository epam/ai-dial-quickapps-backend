from quickapp.common.tool_fallback.base_strategy import BaseStrategy
from quickapp.common.tool_fallback.utils import compose_tool_error_fallback_message
from quickapp.config.tools.tool_fallback import ContinueStrategyModel


class ContinueStrategyHandler(BaseStrategy[ContinueStrategyModel]):
    @staticmethod
    def handle(strategy_config: ContinueStrategyModel, error: Exception) -> str:
        message = compose_tool_error_fallback_message(
            instructions=strategy_config.instructions,
            error=error,
            forward_tool_error_message=strategy_config.forward_tool_error_message,
        )
        if message:
            return message

        return (
            "An error occurs, try to call another applicable tool with the same functionality. "
            "If no such tool is available, notify user that something went wrong during tool calling but you're trying to use your own knowledge to proceed and provide the result."
        )
