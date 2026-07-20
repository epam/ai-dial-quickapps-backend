from quickapp.common.exceptions.fallback_agent_stop import FallbackAgentStopException
from quickapp.common.tool_fallback.base_strategy import BaseStrategy
from quickapp.config.tools.tool_fallback import StopStrategyModel


class StopStrategyHandler(BaseStrategy[StopStrategyModel]):
    @staticmethod
    def handle(strategy_config: StopStrategyModel, error: Exception) -> str:
        raise FallbackAgentStopException()
