from aidial_sdk.chat_completion import Response

from quickapp.common.deployment_usage import DeploymentUsage, ModelUsage


def aggregate_usage_per_model(usages: list[DeploymentUsage]) -> list[ModelUsage]:
    """Sums tokens per model, keeping the order in which models first appear."""
    by_model: dict[str, ModelUsage] = {}
    for usage in usages:
        entry = by_model.setdefault(usage.model_name, ModelUsage(model=usage.model_name))
        entry.prompt_tokens += usage.prompt_tokens
        entry.completion_tokens += usage.completion_tokens
    return list(by_model.values())


def report_usage_per_model(response: Response, usages: list[DeploymentUsage]) -> None:
    """Tells the caller which models this app used (DIAL ``statistics.usage_per_model``)."""
    for model_usage in aggregate_usage_per_model(usages):
        response.add_usage_per_model(
            model_usage.model, model_usage.prompt_tokens, model_usage.completion_tokens
        )
