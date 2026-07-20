import logging

from quickapp.common.exceptions.fallback_agent_stop import FallbackAgentStopException
from quickapp.common.lifecycle_logging import format_event
from quickapp.common.tool_fallback.base_strategy import BaseStrategy
from quickapp.config.tools.tool_fallback import StopStrategyModel

logger = logging.getLogger(__name__)


class StopStrategyHandler(BaseStrategy[StopStrategyModel]):
    @staticmethod
    def handle(strategy_config: StopStrategyModel, error: Exception, tool_call_id: str) -> str:
        logger.info(
            format_event(
                "Fallback applied", tool_call_id=tool_call_id, strategy=strategy_config.type
            )
        )
        raise FallbackAgentStopException()
