from unittest.mock import MagicMock

from quickapp.config.tool_discovery import ToolDiscoveryConfig
from quickapp.config.tools.base import (
    OpenAiToolConfig,
    OpenAiToolFunction,
    OpenAiToolFunctionParameters,
)
from quickapp.config.tools.rest_api import (
    RestApiEndpointConstParam,
    RestApiEndpointHeaderParamInfo,
    RestApiEndpointMethodInfo,
    RestApiEndpointSimpleTypeParam,
    RestApiTool,
    ToolEndpointInfoMethodType,
    ToolEndpointParamType,
)
from quickapp.config.toolsets.rest_api import RestApiToolSet
from quickapp.shared.deferred_tools._deferred_tools_context import (
    DeferredToolsContext,
    is_toolset_deferred,
)


def _make_toolset(deferred: bool | None = None) -> RestApiToolSet:
    return RestApiToolSet(name="my-toolset", deferred=deferred, tools=[])


def _make_discovery_config(
    enabled: bool = True, min_tools_for_deferral: int = 5
) -> ToolDiscoveryConfig:
    return ToolDiscoveryConfig(enabled=enabled, min_tools_for_deferral=min_tools_for_deferral)


class TestIsToolsetDeferred:
    def test_deferred_true_above_threshold_is_deferred(self):
        assert (
            is_toolset_deferred(_make_toolset(True), _make_discovery_config(), tool_count=5) is True
        )

    def test_unset_defaults_to_deferred(self):
        """`deferred` unset (None) behaves the same as `deferred: true`."""
        assert (
            is_toolset_deferred(_make_toolset(None), _make_discovery_config(), tool_count=5) is True
        )

    def test_explicit_false_is_never_deferred_even_above_threshold(self):
        assert (
            is_toolset_deferred(_make_toolset(False), _make_discovery_config(), tool_count=50)
            is False
        )

    def test_below_threshold_is_not_deferred(self):
        assert (
            is_toolset_deferred(_make_toolset(True), _make_discovery_config(), tool_count=4)
            is False
        )

    def test_at_threshold_boundary_is_deferred(self):
        cfg = _make_discovery_config(min_tools_for_deferral=5)
        assert is_toolset_deferred(_make_toolset(True), cfg, tool_count=5) is True

    def test_discovery_disabled_is_never_deferred(self):
        cfg = _make_discovery_config(enabled=False)
        assert is_toolset_deferred(_make_toolset(True), cfg, tool_count=50) is False

    def test_discovery_config_none_is_never_deferred(self):
        assert is_toolset_deferred(_make_toolset(True), None, tool_count=50) is False


def _make_rest_api_tool_with_const_param(name: str = "test_tool") -> RestApiTool:
    return RestApiTool(
        rest_api_method_info=RestApiEndpointMethodInfo(
            method_url="https://example.com", method_type=ToolEndpointInfoMethodType.get
        ),
        open_ai_tool=OpenAiToolConfig(
            function=OpenAiToolFunction(
                name=name,
                description="A test tool",
                parameters=OpenAiToolFunctionParameters(
                    type="object",
                    properties={
                        "query": RestApiEndpointSimpleTypeParam(
                            type="string",
                            description="Query param",
                            parameter_info=RestApiEndpointHeaderParamInfo(
                                type=ToolEndpointParamType.query, key="query"
                            ),
                        ),
                        "api_key": RestApiEndpointConstParam(
                            type=None,
                            const="secret-value",
                            parameter_info=RestApiEndpointHeaderParamInfo(
                                type=ToolEndpointParamType.header, key="X-Api-Key"
                            ),
                        ),
                    },
                ),
            )
        ),
    )


def _make_staged_tool(tool_config, enrich_side_effect=None) -> MagicMock:
    staged_tool = MagicMock()
    staged_tool.tool_config = tool_config
    staged_tool.enrich_openai_tool_schema.side_effect = enrich_side_effect or (lambda t: t)
    return staged_tool


class TestRegisterStagedTools:
    def test_catalog_contains_name_and_description(self):
        context = DeferredToolsContext()
        tool_config = _make_rest_api_tool_with_const_param()
        context.register_staged_tools([_make_staged_tool(tool_config)])

        assert context.catalog == [{"name": "test_tool", "description": "A test tool"}]

    def test_deferred_names_reflects_registered_tools(self):
        context = DeferredToolsContext()
        context.register_staged_tools(
            [_make_staged_tool(_make_rest_api_tool_with_const_param("tool_a"))]
        )

        assert context.deferred_names == frozenset({"tool_a"})

    def test_definition_strips_const_params_same_as_eager_path(self):
        """Regression: a discovered tool's schema must match the eager path — const params
        (fixed values hidden from the LLM) must not leak into the schema surfaced via tool_search.
        """
        context = DeferredToolsContext()
        tool_config = _make_rest_api_tool_with_const_param()
        context.register_staged_tools([_make_staged_tool(tool_config)])

        definition = context.get_definition("test_tool")

        assert definition is not None
        properties = definition["function"]["parameters"]["properties"]
        assert "query" in properties
        assert "api_key" not in properties

    def test_definition_applies_enrich_openai_tool_schema(self):
        """The per-tool enrich_openai_tool_schema hook runs for deferred tools too."""

        def enrich(open_ai_tool: OpenAiToolConfig) -> OpenAiToolConfig:
            enriched = open_ai_tool.model_copy(deep=True)
            enriched.function.description = "enriched"
            return enriched

        context = DeferredToolsContext()
        tool_config = _make_rest_api_tool_with_const_param()
        context.register_staged_tools([_make_staged_tool(tool_config, enrich_side_effect=enrich)])

        definition = context.get_definition("test_tool")
        assert definition is not None
        assert definition["function"]["description"] == "enriched"

    def test_get_definition_returns_none_for_unknown_name(self):
        context = DeferredToolsContext()
        assert context.get_definition("does_not_exist") is None

    def test_ignores_tools_without_openai_tool_config(self):
        context = DeferredToolsContext()
        non_openai_staged_tool = MagicMock()
        non_openai_staged_tool.tool_config = MagicMock()  # not a BaseOpenAITool instance

        context.register_staged_tools([non_openai_staged_tool])

        assert context.catalog == []
        assert context.deferred_names == frozenset()
