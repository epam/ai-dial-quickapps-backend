from quickapp.common.tool_fallback.base_strategy import BaseStrategy
from quickapp.common.tool_fallback.utils import extract_error_content
from quickapp.config.tools.tool_fallback import RetryStrategyModel


class RetryStrategyHandler(BaseStrategy[RetryStrategyModel]):
    _DEFAULT_INSTRUCTIONS = (
        "An error occurs, try to analyze what went wrong and retry the operation."
    )

    @staticmethod
    def handle(strategy_config: RetryStrategyModel, error: Exception) -> str:
        instructions = strategy_config.instructions or RetryStrategyHandler._DEFAULT_INSTRUCTIONS
        if strategy_config.forward_tool_error_message:
            content = extract_error_content(error)
            return f"{content}\n\n{instructions}"
        return instructions
