from quickapp.common.tool_fallback.base_strategy import BaseStrategy
from quickapp.config.tools.tool_fallback import RetryStrategyModel


class RetryStrategyHandler(BaseStrategy[RetryStrategyModel]):
    @staticmethod
    def handle(strategy_config: RetryStrategyModel, error: Exception) -> str:
        if strategy_config.instructions:
            return strategy_config.instructions

        return "An error occurs, try to analyze what went wrong and retry the operation."
