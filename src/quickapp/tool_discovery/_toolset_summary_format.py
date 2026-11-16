from quickapp.common.deferred_tool_types import DeferredToolsetSummary


def format_toolset_summaries(summaries: list[DeferredToolsetSummary]) -> str:
    """Render deferred-toolset summaries as a bullet list: name, tool count, description."""
    lines = [_format_one(summary) for summary in summaries]
    return "\n".join(lines)


def _format_one(summary: DeferredToolsetSummary) -> str:
    line = f"- {summary['name']}. Available tools: {summary['tool_count']}."
    if summary["description"]:
        line += f" {summary['description']}"
    return line
