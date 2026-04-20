from typing import Any

from quickapp.common import CompletionResult
from quickapp.common.exceptions import TOOL_TIMEOUT_PHRASE, ToolTimeoutError
from quickapp.common.tool_fallback.applicable_mixin import ApplicableStrategyMixin
from quickapp.common.tool_fallback.base_strategy import BaseStrategy
from quickapp.common.tool_fallback.mapping import STRATEGY_TYPE_TO_HANDLER
from quickapp.config.tools.tool_fallback import ToolFallbackStrategyModel


def _format_timeout_message(error: ToolTimeoutError) -> str:
    """Long-form LLM-facing message for `ToolTimeoutError`.

    Distinct from `ToolTimeoutError.__str__` (short form shown in stage UI):
    this wording gives the model agency to retry / chunk / inform the user.
    Both forms contain the `TOOL_TIMEOUT_PHRASE` so explicit fallback triggers
    still match against either representation.
    """
    return (
        f"The tool call `{error.tool_name}` {TOOL_TIMEOUT_PHRASE} after "
        f"{error.timeout_seconds} seconds. Consider retrying with a smaller or "
        "different input, breaking the request into smaller pieces, or informing "
        "the user that the operation is taking longer than expected."
    )


class FallbackProcessor(ApplicableStrategyMixin):
    @staticmethod
    def process_fallback(
        strategies: list[ToolFallbackStrategyModel], tool_call_id: str, error: Exception
    ):
        if isinstance(error, ToolTimeoutError):
            return FallbackProcessor._process_timeout(strategies, tool_call_id, error)

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
    def _process_timeout(
        strategies: list[ToolFallbackStrategyModel],
        tool_call_id: str,
        error: ToolTimeoutError,
    ) -> CompletionResult:
        for strategy in strategies:
            if strategy.trigger_on is None:
                continue
            if not FallbackProcessor._is_applicable(strategy, error):
                continue
            strategy_message = FallbackProcessor._handle_fallback_strategy(strategy, error)
            if strategy_message:
                return CompletionResult(
                    content=strategy_message,
                    tool_call_id=tool_call_id,
                    content_type="text/markdown",
                )

        return CompletionResult(
            content=_format_timeout_message(error),
            tool_call_id=tool_call_id,
            content_type="text/markdown",
        )

    @staticmethod
    def _handle_fallback_strategy(
        strategy_config: ToolFallbackStrategyModel, error: Exception
    ) -> str:
        handler_cls: type[BaseStrategy[Any]] | None = STRATEGY_TYPE_TO_HANDLER.get(
            strategy_config.type
        )
        if not handler_cls:
            return ""
        return handler_cls.handle(strategy_config, error)
