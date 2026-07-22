from quickapp.common.tool_fallback.base_strategy import BaseStrategy
from quickapp.common.tool_fallback.utils import compose_tool_error_fallback_message
from quickapp.config.tools.tool_fallback import RetryStrategyModel


class RetryStrategyHandler(BaseStrategy[RetryStrategyModel]):
    _DEFAULT_INSTRUCTIONS = (
        "An error occurs, try to analyze what went wrong and retry the operation."
    )

    @staticmethod
    def handle(strategy_config: RetryStrategyModel, error: Exception) -> str:
        return compose_tool_error_fallback_message(
            instructions=strategy_config.instructions or RetryStrategyHandler._DEFAULT_INSTRUCTIONS,
            error=error,
            forward_tool_error_message=strategy_config.forward_tool_error_message,
        )
