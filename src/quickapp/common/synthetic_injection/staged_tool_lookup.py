import logging

from quickapp.common.staged_base_tool import StagedBaseTool


def build_staged_tool_index(tools: list[StagedBaseTool]) -> dict[str, StagedBaseTool]:
    """Index staged tools by their sanitized OpenAI function name, the key every
    synthetic injector looks tools up by."""
    return {tool.tool_config.open_ai_tool.function.name: tool for tool in tools}


def find_staged_tool(
    tools: dict[str, StagedBaseTool], tool_name: str, logger: logging.Logger, caller: str
) -> StagedBaseTool | None:
    """The tool registered under *tool_name*, or ``None`` with a warning logged
    under *caller* — the class name a synthetic injector identifies itself with."""
    tool = tools.get(tool_name)
    if tool is None:
        logger.warning("%s: tool '%s' not found in staged tools, skipping", caller, tool_name)
    return tool
