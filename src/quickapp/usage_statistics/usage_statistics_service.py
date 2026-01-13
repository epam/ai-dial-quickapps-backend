from typing import Literal

from aidial_sdk.chat_completion import Choice
from injector import inject

from quickapp.common.deployment_usage import DeploymentUsage
from quickapp.usage_statistics._aggregated_stats import _AggregatedStats
from quickapp.usage_statistics._pricing_service import _PricingService
from quickapp.usage_statistics._usage_statistics_renderer import _UsageStatisticsRenderer


@inject
class UsageStatisticsService:
    def __init__(self, pricing_service: _PricingService, choice: Choice):
        self.__pricing_service: _PricingService = pricing_service
        self.__choice: Choice = choice

    async def process_usage_statistics(self, usage_per_deployment: list[DeploymentUsage]):
        if len(usage_per_deployment) == 0:
            return
        aggregated = dict[str, _AggregatedStats]()
        for usage in usage_per_deployment:
            total_cost = await self._calculate_total_cost(usage)

            key = usage.deployment_name
            if key not in aggregated:
                aggregated[key] = _AggregatedStats(
                    usage.deployment_name,
                    usage.model_name if usage.is_orchestrator() else usage.deployment_id,
                    usage.prompt_tokens if usage.is_orchestrator() else "-",
                    usage.completion_tokens if usage.is_orchestrator() else "-",
                    total_cost if isinstance(total_cost, float) else "-",
                )
            else:
                if usage.is_orchestrator():
                    aggregated[key].add_prompt_tokens(usage.prompt_tokens)
                    aggregated[key].add_completion_tokens(usage.completion_tokens)
                aggregated[key].add_total_cost(total_cost)

        markdown_table = _UsageStatisticsRenderer.render_usage_statistics_table(
            list(aggregated.values())
        )

        with self.__choice.create_stage("Usage Statistics") as stage:
            stage.append_content(markdown_table)

    @staticmethod
    def __calculate_costs(
        tokens_count: int | Literal["-"], price: float | Literal["-"]
    ) -> float | Literal["-"]:
        if isinstance(price, float) and isinstance(tokens_count, int):
            return round(tokens_count * price, 7)
        else:
            return "-"

    async def _calculate_total_cost(self, usage: DeploymentUsage) -> float | Literal["-"]:
        pricing_data = await self.__pricing_service.get_price(usage.model_name)
        prompt_cost = self.__calculate_costs(usage.prompt_tokens, pricing_data.input_token_price)
        completion_cost = self.__calculate_costs(
            usage.completion_tokens, pricing_data.output_token_price
        )
        return (
            round(prompt_cost + completion_cost, 7)
            if isinstance(prompt_cost, float) and isinstance(completion_cost, float)
            else "-"
        )
