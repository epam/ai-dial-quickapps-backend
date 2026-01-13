from quickapp.common.deployment_usage import ORCHESTRATOR
from quickapp.usage_statistics._aggregated_stats import _AggregatedStats


class _UsageStatisticsRenderer:
    @staticmethod
    def render_usage_statistics_table(aggregated_stats: list[_AggregatedStats]):
        markdown_table = (
            "| Orchestrator/Tool | Deployment ID | Prompt Tokens | Completion Tokens | Cost, $ |\n"
            "|-----------------|---------------|---------------|-------------------|------|\n"
        )

        orchestrator_stat = next(
            (stat for stat in aggregated_stats if stat.deployment_name == ORCHESTRATOR), None
        )

        total_cost: float = 0
        all_costs_presented = True

        # Add the orchestrator stat first if it exists
        if orchestrator_stat:
            markdown_table += (
                f"| {orchestrator_stat.deployment_name} | {orchestrator_stat.deployment_id} | "
                f"{orchestrator_stat.total_prompt_tokens} | {orchestrator_stat.total_completion_tokens} | {orchestrator_stat.total_cost} |\n"
            )
            if isinstance(orchestrator_stat.total_cost, float):
                total_cost += orchestrator_stat.total_cost
            else:
                all_costs_presented = False

        for stat in aggregated_stats:
            if stat == orchestrator_stat:
                continue
            markdown_table += f"| {"Tool"} | {stat.deployment_id} | {stat.total_prompt_tokens} | {stat.total_completion_tokens} | {stat.total_cost} |\n"
            if isinstance(stat.total_cost, float):
                total_cost += stat.total_cost
            else:
                all_costs_presented = False

        if all_costs_presented:
            markdown_table += f"| **Total** | - | - | - | **{round(total_cost, 7)}** |\n"

        return markdown_table
