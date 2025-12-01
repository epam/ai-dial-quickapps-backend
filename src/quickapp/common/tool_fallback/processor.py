from typing import Any, Type

from quickapp.common import CompletionResult
from quickapp.common.tool_fallback.applicable_mixin import ApplicableStrategyMixin
from quickapp.common.tool_fallback.base_strategy import BaseStrategy
from quickapp.common.tool_fallback.mapping import STRATEGY_TYPE_TO_HANDLER
from quickapp.config.tools.tool_fallback import ToolFallbackStrategyModel


class FallbackProcessor(ApplicableStrategyMixin):
    @staticmethod
    def process_fallback(
        strategies: list[ToolFallbackStrategyModel], tool_call_id: str, error: Exception
    ):
        message: str = ""
        for strategy in strategies:
            if FallbackProcessor._is_applicable(strategy, error):
                strategy_message = FallbackProcessor._handle_fallback_strategy(strategy, error)
                if strategy_message:
                    message = strategy_message
                    break

        if not message:
            raise error

        return CompletionResult(
            content=message, tool_call_id=tool_call_id, content_type="text/markdown"
        )

    @staticmethod
    def _handle_fallback_strategy(
        strategy_config: ToolFallbackStrategyModel, error: Exception
    ) -> str:
        handler_cls: Type[BaseStrategy[Any]] | None = STRATEGY_TYPE_TO_HANDLER.get(
            strategy_config.type
        )
        if not handler_cls:
            return ""
        return handler_cls.handle(strategy_config, error)
