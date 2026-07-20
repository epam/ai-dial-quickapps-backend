from quickapp.common.tool_fallback.base_strategy import BaseStrategy
from quickapp.common.tool_fallback.utils import extract_error_content
from quickapp.config.tools.tool_fallback import RetryStrategyModel


class RetryStrategyHandler(BaseStrategy[RetryStrategyModel]):
    @staticmethod
    def handle(strategy_config: RetryStrategyModel, error: Exception) -> str:
        content = extract_error_content(error)
        if strategy_config.trigger_on is not None and strategy_config.instructions:
            return f"{content}\n\n{strategy_config.instructions}"
        return content
