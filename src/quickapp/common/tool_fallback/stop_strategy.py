import logging

from quickapp.common.lifecycle_logging import format_event
from quickapp.common.tool_fallback.base_strategy import BaseStrategy
from quickapp.common.tool_fallback.utils import compose_fallback_content
from quickapp.config.tools.tool_fallback import StopStrategyModel

logger = logging.getLogger(__name__)

_STOP_INSTRUCTION = (
    "STOP: Execution halted due to a tool error. "
    "You *MUST* inform the user that execution stopped because of this error "
    "and *MUST NOT* proceed further."
)


class StopStrategyHandler(BaseStrategy[StopStrategyModel]):
    @staticmethod
    def handle(strategy_config: StopStrategyModel, error: Exception, tool_call_id: str) -> str:
        result = compose_fallback_content(error, _STOP_INSTRUCTION)
        logger.info(
            format_event(
                "Fallback applied", tool_call_id=tool_call_id, strategy=strategy_config.type
            )
        )
        return result
