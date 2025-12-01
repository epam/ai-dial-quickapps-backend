from typing import Any, Dict, Type

from quickapp.common.tool_fallback.base_strategy import BaseStrategy
from quickapp.common.tool_fallback.continue_strategy import ContinueStrategyHandler
from quickapp.common.tool_fallback.stop_strategy import StopStrategyHandler

STRATEGY_TYPE_TO_HANDLER: Dict[str, Type[BaseStrategy[Any]]] = {
    "stop": StopStrategyHandler,
    "continue": ContinueStrategyHandler,
}
