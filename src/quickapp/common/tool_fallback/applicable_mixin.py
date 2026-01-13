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
    def _is_applicable_by_trigger_on(trigger_on: TriggerOn, error: Exception) -> bool:
        if trigger_on.type == TriggerOnType.contains:
            return (
                trigger_on.value in str(error)
                if trigger_on.case_sensitive
                else trigger_on.value.lower() in str(error).lower()
            )
        else:
            return (
                trigger_on.value == str(error)
                if trigger_on.case_sensitive
                else trigger_on.value.lower() == str(error).lower()
            )
