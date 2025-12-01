from quickapp.common.tool_fallback.base_strategy import BaseStrategy
from quickapp.config.tools.tool_fallback import StopStrategyModel


class StopStrategyHandler(BaseStrategy[StopStrategyModel]):
    @staticmethod
    def handle(strategy_config: StopStrategyModel, error: Exception) -> str:
        return "STOP: Execution halted due to a tool error. You *MUST* inform the user that execution stopped because of this error and *MUST NOT* proceed further."
