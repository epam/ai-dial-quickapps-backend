from quickapp.common.tool_fallback.base_strategy import BaseStrategy
from quickapp.common.tool_fallback.utils import compose_tool_error_fallback_message
from quickapp.config.tools.tool_fallback import ContinueStrategyModel


class ContinueStrategyHandler(BaseStrategy[ContinueStrategyModel]):
    _DEFAULT_INSTRUCTIONS = (
        "An error occurs, try to call another applicable tool with the same functionality. "
        "If no such tool is available, notify user that something went wrong during tool calling but you're trying to use your own knowledge to proceed and provide the result."
    )

    @staticmethod
    def handle(strategy_config: ContinueStrategyModel, error: Exception) -> str:
        return compose_tool_error_fallback_message(
            instructions=strategy_config.instructions
            or ContinueStrategyHandler._DEFAULT_INSTRUCTIONS,
            error=error,
            forward_tool_error_message=strategy_config.forward_tool_error_message,
        )
