from unittest.mock import MagicMock

from quickapp.common.tool_fallback.catch_all_scanner import log_customised_catch_all_strategies
from quickapp.config.tools.tool_fallback import ContinueStrategyModel, ToolFallbackConfig
from quickapp.config.toolsets.mcp import MCPProtocol, MCPServerInfo, MCPToolSet


def _app_config(tool_sets):
    cfg = MagicMock()
    cfg.tool_sets = tool_sets
    return cfg


def test_logs_for_mcp_toolset_with_customised_catchall(caplog):
    mcp = MCPToolSet(
        name="my-mcp",
        mcp_server_info=MCPServerInfo(
            url="https://x", authorization=None, protocol=MCPProtocol.sse
        ),
        fallback_configuration=ToolFallbackConfig(
            strategies=[ContinueStrategyModel(instructions="customised")]
        ),
    )
    with caplog.at_level("INFO"):
        log_customised_catch_all_strategies(_app_config([mcp]))
    assert any("my-mcp" in r.message for r in caplog.records)


def test_no_log_when_catchall_has_no_instructions(caplog):
    mcp = MCPToolSet(
        name="silent-mcp",
        mcp_server_info=MCPServerInfo(
            url="https://x", authorization=None, protocol=MCPProtocol.sse
        ),
        fallback_configuration=ToolFallbackConfig(strategies=[ContinueStrategyModel()]),
    )
    with caplog.at_level("INFO"):
        log_customised_catch_all_strategies(_app_config([mcp]))
    assert not any("silent-mcp" in r.message for r in caplog.records)


def test_logs_for_toolset_with_tools(caplog):
    tool = MagicMock()
    tool.fallback_configuration = ToolFallbackConfig(
        strategies=[ContinueStrategyModel(instructions="customised")]
    )
    tool.open_ai_tool.function.name = "my_tool"
    toolset = MagicMock()
    toolset.name = "rest-set"
    toolset.tools = [tool]
    # Not MCP/DialMCP - bypass isinstance checks; use MagicMock spec avoidance
    # But the scanner checks isinstance(tool_set, (MCPToolSet, DialMCPToolSet)).
    # MagicMock won't be an instance of those, so it will go through the tools branch.
    with caplog.at_level("INFO"):
        log_customised_catch_all_strategies(_app_config([toolset]))
    assert any("my_tool" in r.message and "rest-set" in r.message for r in caplog.records)
