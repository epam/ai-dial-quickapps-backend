from unittest.mock import MagicMock

from fastapi_injector import Injected
from injector import Binder, InstanceProvider
from starlette.testclient import TestClient

from quickapp.common import StagedBaseTool
from quickapp.common.deferred_tool_types import DeferredToolCatalogEntry, DeferredToolsetSummary
from quickapp.common.tool_names import INTERNAL_CODE_EXECUTION_PYTHON_INTERPRETER_TOOL_NAME
from quickapp.config.application import ApplicationConfig
from quickapp.config.tool_discovery import ToolDiscoveryConfig
from quickapp.config.tools.base import (
    OpenAiToolConfig,
    OpenAiToolFunction,
    OpenAiToolFunctionParameters,
)
from quickapp.config.tools.internal import InternalTool
from quickapp.config.toolsets.internal import InternalToolSet
from quickapp.internal_tooling._internal_deferred_tools_context import _InternalDeferredToolsContext
from quickapp.internal_tooling.internal_tooling_module import InternalToolModule
from quickapp.internal_tooling.py_interpreter_tooling._py_interpreter_tool import _PyInterpreterTool
from tests.unit_tests.common import create_test_app


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


class _StubPyTool:
    def __init__(self, tool_config: InternalTool, name: str, description: str | None) -> None:
        self.tool_config = tool_config

    def enrich_openai_tool_schema(self, open_ai_tool: OpenAiToolConfig) -> OpenAiToolConfig:
        return open_ai_tool


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
        deferred_context = MagicMock(spec=_InternalDeferredToolsContext)

        module = InternalToolModule()
        result = module._provide_internal_tools(app_config, py_builder, deferred_context)

        assert result == [staged_tool]
        deferred_context.register_deferred_tools.assert_called_once_with(toolset, [staged_tool])

    def test_does_not_defer_below_threshold(self):
        tool_config = _make_internal_tool_config()
        toolset = InternalToolSet(name="internal", deferred=True, tools=[tool_config])
        discovery_cfg = ToolDiscoveryConfig(enabled=True, min_tools_for_deferral=5)
        app_config = _make_app_config(toolset, discovery_cfg)
        staged_tool, py_builder = _make_py_builder(tool_config)
        deferred_context = MagicMock(spec=_InternalDeferredToolsContext)

        module = InternalToolModule()
        result = module._provide_internal_tools(app_config, py_builder, deferred_context)

        assert result == [staged_tool]
        deferred_context.register_deferred_tools.assert_not_called()

    def test_does_not_defer_when_discovery_disabled(self):
        tool_config = _make_internal_tool_config()
        toolset = InternalToolSet(name="internal", deferred=True, tools=[tool_config])
        app_config = _make_app_config(toolset, discovery_cfg=None)
        staged_tool, py_builder = _make_py_builder(tool_config)
        deferred_context = MagicMock(spec=_InternalDeferredToolsContext)

        module = InternalToolModule()
        result = module._provide_internal_tools(app_config, py_builder, deferred_context)

        assert result == [staged_tool]
        deferred_context.register_deferred_tools.assert_not_called()


def test_repeated_tool_resolution_does_not_grow_deferred_registry():
    """Regression (#707): `list[StagedBaseTool]` re-runs per injection; registration is idempotent."""
    tool_config = _make_internal_tool_config()
    toolset = InternalToolSet(name="internal", deferred=True, tools=[tool_config])
    app_config = _make_app_config(
        toolset, ToolDiscoveryConfig(enabled=True, min_tools_for_deferral=1)
    )

    def configure(binder: Binder):
        binder.bind(ApplicationConfig, to=InstanceProvider(app_config))
        binder.bind(_PyInterpreterTool, to=_StubPyTool)  # AssistedBuilder needs a class provider

    app = create_test_app([InternalToolModule, configure])

    @app.get("/")
    async def get_method(
        first: list[StagedBaseTool] = Injected(list[StagedBaseTool]),
        second: list[StagedBaseTool] = Injected(list[StagedBaseTool]),
        summaries: list[DeferredToolsetSummary] = Injected(list[DeferredToolsetSummary]),
        catalog: list[DeferredToolCatalogEntry] = Injected(list[DeferredToolCatalogEntry]),
    ):
        assert len(first) == len(second) == 1
        assert len(summaries) == 1
        assert len(catalog) == 1
        return {}

    assert TestClient(app).get("/").status_code == 200
