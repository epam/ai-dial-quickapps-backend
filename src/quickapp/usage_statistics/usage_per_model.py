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


def report_usage(response: Response, usages: list[DeploymentUsage]) -> None:
    """Tells the caller which models this app used (DIAL ``statistics.usage_per_model``) and the total ``usage``."""
    per_model = aggregate_usage_per_model(usages)
    for model_usage in per_model:
        response.add_usage_per_model(
            model_usage.model, model_usage.prompt_tokens, model_usage.completion_tokens
        )
    if per_model:
        response.set_usage(
            sum(m.prompt_tokens for m in per_model),
            sum(m.completion_tokens for m in per_model),
        )
