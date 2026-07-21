from quickapp.common.exceptions.tool_error import ToolErrorException
from quickapp.config.tools.tool_fallback import ToolFallbackStrategyModel, TriggerOn, TriggerOnType


class ApplicableStrategyMixin:
    @staticmethod
    def _is_applicable(strategy_config: ToolFallbackStrategyModel, error: Exception) -> bool:
        if trigger_on := strategy_config.trigger_on:
            if trigger_on and not ApplicableStrategyMixin._is_applicable_by_trigger_on(
                trigger_on, error
            ):
                return False
        return True

    @staticmethod
    def _matchable_text(error: Exception) -> str:
        # Match trigger_on against the real tool error body (error_message), not the
        # structural str(e): the exception's string form carries no response body under
        # the content rule (#436), but trigger matching must still see the error text.
        if isinstance(error, ToolErrorException):
            return error.error_message
        return str(error)

    @staticmethod
    def _is_applicable_by_trigger_on(trigger_on: TriggerOn, error: Exception) -> bool:
        text = ApplicableStrategyMixin._matchable_text(error)
        if trigger_on.type == TriggerOnType.contains:
            return (
                trigger_on.value in text
                if trigger_on.case_sensitive
                else trigger_on.value.lower() in text.lower()
            )
        else:
            return (
                trigger_on.value == text
                if trigger_on.case_sensitive
                else trigger_on.value.lower() == text.lower()
            )
