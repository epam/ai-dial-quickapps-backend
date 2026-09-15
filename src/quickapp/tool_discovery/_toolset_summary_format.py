def format_toolset_summaries(summaries: list[dict[str, str | int | None]]) -> str:
    """Render deferred-toolset summaries as a bullet list: name, tool count, description."""
    lines = [_format_one(summary) for summary in summaries]
    return "\n".join(lines)


def _format_one(summary: dict[str, str | int | None]) -> str:
    line = f"- {summary['name']}. Available tools: {summary['tool_count']}."
    if summary["description"]:
        line += f" {summary['description']}"
    return line
