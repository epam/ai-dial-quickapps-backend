import logging

from quickapp.common.lifecycle_logging import format_event
from quickapp.common.tool_fallback.base_strategy import BaseStrategy
from quickapp.common.tool_fallback.utils import compose_fallback_content
from quickapp.config.tools.tool_fallback import ContinueStrategyModel

logger = logging.getLogger(__name__)


class ContinueStrategyHandler(BaseStrategy[ContinueStrategyModel]):
    @staticmethod
    def handle(strategy_config: ContinueStrategyModel, error: Exception, tool_call_id: str) -> str:
        result = compose_fallback_content(error, strategy_config.instructions)
        logger.info(
            format_event(
                "Fallback applied", tool_call_id=tool_call_id, strategy=strategy_config.type
            )
        )
        return result
