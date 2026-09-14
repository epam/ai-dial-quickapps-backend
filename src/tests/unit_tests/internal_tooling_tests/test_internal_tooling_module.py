from unittest.mock import MagicMock

from quickapp.common.tool_names import INTERNAL_CODE_EXECUTION_PYTHON_INTERPRETER_TOOL_NAME
from quickapp.config.tool_discovery import ToolDiscoveryConfig
from quickapp.config.tools.base import (
    OpenAiToolConfig,
    OpenAiToolFunction,
    OpenAiToolFunctionParameters,
)
from quickapp.config.tools.internal import InternalTool
from quickapp.config.toolsets.internal import InternalToolSet
from quickapp.internal_tooling.internal_tooling_module import InternalToolModule
from quickapp.shared.deferred_tools import DeferredToolsContext


def _make_internal_tool_config(
    name: str = INTERNAL_CODE_EXECUTION_PYTHON_INTERPRETER_TOOL_NAME,
) -> InternalTool:
    return InternalTool(
        open_ai_tool=OpenAiToolConfig(
            function=OpenAiToolFunction(
                name=name,
                description="Runs python code",
                parameters=OpenAiToolFunctionParameters(type="object", properties={}),
            )
        )
    )


def _make_app_config(
    toolset: InternalToolSet, discovery_cfg: ToolDiscoveryConfig | None
) -> MagicMock:
    app_config = MagicMock()
    app_config.tool_sets = [toolset]
    app_config.orchestrator.tool_discovery = discovery_cfg
    return app_config


def _make_py_builder(tool_config: InternalTool) -> MagicMock:
    staged_tool = MagicMock()
    staged_tool.tool_config = tool_config
    builder = MagicMock()
    builder.build.return_value = staged_tool
    return staged_tool, builder


class TestProvideInternalTools:
    def test_registers_deferred_toolset_with_deferred_context(self):
        tool_config = _make_internal_tool_config()
        toolset = InternalToolSet(name="internal", deferred=True, tools=[tool_config])
        discovery_cfg = ToolDiscoveryConfig(enabled=True, min_tools_for_deferral=1)
        app_config = _make_app_config(toolset, discovery_cfg)
        staged_tool, py_builder = _make_py_builder(tool_config)
        deferred_context = MagicMock(spec=DeferredToolsContext)

        module = InternalToolModule()
        result = module._provide_internal_tools(app_config, py_builder, deferred_context)

        assert result == [staged_tool]
        deferred_context.register_staged_tools.assert_called_once_with([staged_tool])

    def test_does_not_defer_below_threshold(self):
        tool_config = _make_internal_tool_config()
        toolset = InternalToolSet(name="internal", deferred=True, tools=[tool_config])
        discovery_cfg = ToolDiscoveryConfig(enabled=True, min_tools_for_deferral=5)
        app_config = _make_app_config(toolset, discovery_cfg)
        staged_tool, py_builder = _make_py_builder(tool_config)
        deferred_context = MagicMock(spec=DeferredToolsContext)

        module = InternalToolModule()
        result = module._provide_internal_tools(app_config, py_builder, deferred_context)

        assert result == [staged_tool]
        deferred_context.register_staged_tools.assert_not_called()

    def test_does_not_defer_when_discovery_disabled(self):
        tool_config = _make_internal_tool_config()
        toolset = InternalToolSet(name="internal", deferred=True, tools=[tool_config])
        app_config = _make_app_config(toolset, discovery_cfg=None)
        staged_tool, py_builder = _make_py_builder(tool_config)
        deferred_context = MagicMock(spec=DeferredToolsContext)

        module = InternalToolModule()
        result = module._provide_internal_tools(app_config, py_builder, deferred_context)

        assert result == [staged_tool]
        deferred_context.register_staged_tools.assert_not_called()
