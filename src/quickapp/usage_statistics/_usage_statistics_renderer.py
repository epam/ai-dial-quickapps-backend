from quickapp.common.deployment_usage import ORCHESTRATOR
from quickapp.usage_statistics._aggregated_stats import _AggregatedStats


class _UsageStatisticsRenderer:
    @staticmethod
    def render_usage_statistics_table(aggregated_stats: list[_AggregatedStats]):
        markdown_table = (
            "| Orchestrator/Tool | Deployment ID | Prompt Tokens | Completion Tokens | Cost, $ |\n"
            "|-----------------|---------------|---------------|-------------------|------|\n"
        )

        orchestrator_stats = [
            stat for stat in aggregated_stats if stat.deployment_name == ORCHESTRATOR
        ]
        tool_stats = [stat for stat in aggregated_stats if stat.deployment_name != ORCHESTRATOR]

        total_cost: float = 0
        all_costs_presented = True

        for stat in orchestrator_stats:
            markdown_table += _UsageStatisticsRenderer._render_row(stat.deployment_name, stat)
            if isinstance(stat.total_cost, float):
                total_cost += stat.total_cost
            else:
                all_costs_presented = False

        for stat in tool_stats:
            markdown_table += _UsageStatisticsRenderer._render_row(
                f"Tool: {stat.deployment_name}", stat
            )
            if isinstance(stat.total_cost, float):
                total_cost += stat.total_cost
            else:
                all_costs_presented = False

        if all_costs_presented:
            markdown_table += f"| **Total** | - | - | - | **{round(total_cost, 7)}** |\n"

        return markdown_table

    @staticmethod
    def _render_row(label: str, stat: _AggregatedStats) -> str:
        return (
            f"| {label} | {stat.deployment_id} | {stat.total_prompt_tokens} | "
            f"{stat.total_completion_tokens} | {stat.total_cost} |\n"
        )
