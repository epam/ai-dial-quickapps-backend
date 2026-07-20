import logging

from quickapp.common.lifecycle_logging import format_event
from quickapp.common.tool_fallback.base_strategy import BaseStrategy
from quickapp.common.tool_fallback.utils import extract_error_content
from quickapp.config.tools.tool_fallback import RetryStrategyModel

logger = logging.getLogger(__name__)


class RetryStrategyHandler(BaseStrategy[RetryStrategyModel]):
    @staticmethod
    def handle(strategy_config: RetryStrategyModel, error: Exception, tool_call_id: str) -> str:
        content = extract_error_content(error)
        if strategy_config.trigger_on is not None and strategy_config.instructions:
            result = f"{content}\n\n{strategy_config.instructions}"
        else:
            result = content
        logger.info(
            format_event(
                "Fallback applied", tool_call_id=tool_call_id, strategy=strategy_config.type
            )
        )
        return result
