from typing import Any

from quickapp.common.tool_fallback.base_strategy import BaseStrategy
from quickapp.common.tool_fallback.continue_strategy import ContinueStrategyHandler
from quickapp.common.tool_fallback.retry_strategy import RetryStrategyHandler
from quickapp.common.tool_fallback.stop_strategy import StopStrategyHandler

STRATEGY_TYPE_TO_HANDLER: dict[str, type[BaseStrategy[Any]]] = {
    "stop": StopStrategyHandler,
    "continue": ContinueStrategyHandler,
    "retry": RetryStrategyHandler,
}
