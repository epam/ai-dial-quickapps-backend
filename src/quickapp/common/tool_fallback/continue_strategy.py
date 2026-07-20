import logging

from quickapp.common.lifecycle_logging import format_event
from quickapp.common.tool_fallback.base_strategy import BaseStrategy
from quickapp.common.tool_fallback.utils import extract_error_content
from quickapp.config.tools.tool_fallback import ContinueStrategyModel

logger = logging.getLogger(__name__)


class ContinueStrategyHandler(BaseStrategy[ContinueStrategyModel]):
    @staticmethod
    def handle(strategy_config: ContinueStrategyModel, error: Exception, tool_call_id: str) -> str:
        if strategy_config.trigger_on is None and strategy_config.instructions is not None:
            logger.warning(
                "ContinueStrategyModel: instructions on catch-all (no trigger_on) are deprecated "
                "and will be ignored. The tool error message is forwarded to the LLM directly."
            )
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
