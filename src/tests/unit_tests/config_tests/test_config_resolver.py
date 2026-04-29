from copy import deepcopy
from unittest.mock import MagicMock

import pytest

from quickapp.common.exceptions import ConfigResolutionException
from quickapp.config.config_template_resolver import ConfigResolver
from quickapp.config.predefined_content_provider import ContentType, PredefinedContentProvider
from quickapp.config.tools.deployment import DialDeploymentTool
from quickapp.config.tools.predefined import PredefinedTool
from quickapp.config.toolsets.deployment import DeploymentToolSet
from quickapp.config.toolsets.predefined import PredefinedToolSet


def _minimal_deployment_tool_template() -> dict:
    return {
        "type": "deployment-tool",
        "deployment": {"name": "dial-rag"},
        "open_ai_tool": {
            "type": "function",
            "function": {
                "name": "rag_search_tool",
                "description": "Performs RAG search.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Query"},
                    },
                    "required": ["query"],
                },
            },
        },
    }


def _minimal_deployment_toolset_template() -> dict:
    return {
        "name": "chat-hub",
        "type": "dial-deployment",
        "tools": [],
    }


@pytest.fixture
def mock_provider() -> MagicMock:
    return MagicMock(spec=PredefinedContentProvider)


@pytest.fixture
def resolver(mock_provider: MagicMock) -> ConfigResolver:
    return ConfigResolver(mock_provider)


class TestSchemaAcceptsOverride:
    """Group A — `override` field on `PredefinedTool` and `PredefinedToolSet`."""

    def test_predefined_tool_override_defaults_to_none(self):
        tool = PredefinedTool(template_name="dial_rag")
        assert tool.override is None

    def test_predefined_tool_accepts_override_dict(self):
        tool = PredefinedTool(
            template_name="dial_rag",
            override={"deployment": {"name": "hr-rag"}},
        )
        assert tool.override == {"deployment": {"name": "hr-rag"}}

    def test_predefined_toolset_override_defaults_to_none(self):
        ts = PredefinedToolSet(template_name="chathub")
        assert ts.override is None

    def test_predefined_toolset_accepts_override_dict(self):
        ts = PredefinedToolSet(
            template_name="chathub",
            override={"name": "renamed"},
        )
        assert ts.override == {"name": "renamed"}


class TestResolverAppliesMerge:
    """Group B — `ConfigResolver` applies the override patch before validation."""

    def test_resolve_tool_with_no_override_passes_template_through(
        self, resolver: ConfigResolver, mock_provider: MagicMock
    ):
        mock_provider.read_json.return_value = _minimal_deployment_tool_template()
        result = resolver.resolve_tool(PredefinedTool(template_name="dial_rag"))
        assert isinstance(result, DialDeploymentTool)
        assert result.deployment.name == "dial-rag"
        mock_provider.read_json.assert_called_once_with(ContentType.TOOL, "dial_rag")

    def test_resolve_tool_applies_deployment_name_swap(
        self, resolver: ConfigResolver, mock_provider: MagicMock
    ):
        mock_provider.read_json.return_value = _minimal_deployment_tool_template()
        result = resolver.resolve_tool(
            PredefinedTool(
                template_name="dial_rag",
                override={"deployment": {"name": "hr-rag-prod"}},
            )
        )
        assert isinstance(result, DialDeploymentTool)
        assert result.deployment.name == "hr-rag-prod"

    def test_resolve_tool_applies_function_description_revision(
        self, resolver: ConfigResolver, mock_provider: MagicMock
    ):
        mock_provider.read_json.return_value = _minimal_deployment_tool_template()
        result = resolver.resolve_tool(
            PredefinedTool(
                template_name="dial_rag",
                override={
                    "open_ai_tool": {"function": {"description": "Search internal HR docs."}}
                },
            )
        )
        assert isinstance(result, DialDeploymentTool)
        assert result.open_ai_tool.function.description == "Search internal HR docs."
        # Other fields untouched.
        assert result.open_ai_tool.function.name == "rag_search_tool"
        assert result.deployment.name == "dial-rag"

    def test_resolve_tool_does_not_mutate_template(
        self, resolver: ConfigResolver, mock_provider: MagicMock
    ):
        template = _minimal_deployment_tool_template()
        baseline = deepcopy(template)
        mock_provider.read_json.return_value = template
        resolver.resolve_tool(
            PredefinedTool(
                template_name="dial_rag",
                override={"deployment": {"name": "hr-rag-prod"}},
            )
        )
        assert template == baseline

    def test_resolve_predefined_toolset_applies_name_override(
        self, resolver: ConfigResolver, mock_provider: MagicMock
    ):
        mock_provider.read_json.return_value = _minimal_deployment_toolset_template()
        result = resolver.resolve_predefined_toolset(
            PredefinedToolSet(
                template_name="chathub",
                override={"name": "renamed-toolset"},
            )
        )
        assert isinstance(result, DeploymentToolSet)
        assert result.name == "renamed-toolset"


class TestDiscriminatorRejection:
    """Group C — patches that target `type` are rejected at merge time."""

    def test_resolve_tool_override_rejects_top_level_type(
        self, resolver: ConfigResolver, mock_provider: MagicMock
    ):
        mock_provider.read_json.return_value = _minimal_deployment_tool_template()
        with pytest.raises(ConfigResolutionException) as excinfo:
            resolver.resolve_tool(
                PredefinedTool(
                    template_name="dial_rag",
                    override={"type": "rest-api-tool"},
                )
            )
        assert excinfo.value.template_name == "dial_rag"
        assert excinfo.value.json_path == "/type"

    def test_resolve_tool_override_rejects_nested_type_in_object(
        self, resolver: ConfigResolver, mock_provider: MagicMock
    ):
        mock_provider.read_json.return_value = _minimal_deployment_tool_template()
        with pytest.raises(ConfigResolutionException) as excinfo:
            resolver.resolve_tool(
                PredefinedTool(
                    template_name="dial_rag",
                    override={"deployment": {"type": "anything"}},
                )
            )
        assert excinfo.value.json_path == "/deployment/type"

    def test_resolve_predefined_toolset_override_rejects_nested_type_in_tools(
        self, resolver: ConfigResolver, mock_provider: MagicMock
    ):
        mock_provider.read_json.return_value = _minimal_deployment_toolset_template()
        with pytest.raises(ConfigResolutionException) as excinfo:
            resolver.resolve_predefined_toolset(
                PredefinedToolSet(
                    template_name="chathub",
                    override={"tools": [{"type": "rest-api-tool"}]},
                )
            )
        assert excinfo.value.template_name == "chathub"
        assert excinfo.value.json_path == "/tools/0/type"


class TestErrorWrapping:
    """Group D — invalid patches surface as `ConfigResolutionException`."""

    def test_invalid_patch_field_wrapped_with_template_name_and_path(
        self, resolver: ConfigResolver, mock_provider: MagicMock
    ):
        mock_provider.read_json.return_value = _minimal_deployment_tool_template()
        with pytest.raises(ConfigResolutionException) as excinfo:
            # `deployment.name` must be a string; passing an int triggers
            # pydantic validation after the merge.
            resolver.resolve_tool(
                PredefinedTool(
                    template_name="dial_rag",
                    override={"deployment": {"name": 123}},
                )
            )
        assert excinfo.value.template_name == "dial_rag"
        # First pydantic error's loc, joined by '/' and prefixed with '/'.
        assert "deployment" in excinfo.value.json_path
        assert "name" in excinfo.value.json_path
        assert excinfo.value.details

    def test_resolve_predefined_toolset_validation_error_wrapped(
        self, resolver: ConfigResolver, mock_provider: MagicMock
    ):
        mock_provider.read_json.return_value = _minimal_deployment_toolset_template()
        with pytest.raises(ConfigResolutionException) as excinfo:
            resolver.resolve_predefined_toolset(
                PredefinedToolSet(
                    template_name="chathub",
                    override={"name": 99},  # name must be a string
                )
            )
        assert excinfo.value.template_name == "chathub"


class TestOverrideOnDisabledTool:
    """Group E — `enabled: false` short-circuits before the override is evaluated."""

    def test_resolve_toolset_skips_disabled_predefined_tool_with_override(
        self, resolver: ConfigResolver, mock_provider: MagicMock
    ):
        disabled_ref = PredefinedTool(
            template_name="dial_rag",
            enabled=False,
            override={"deployment": {"name": "never-applied"}},
        )
        toolset = DeploymentToolSet(name="chat-hub", tools=[disabled_ref])

        result = resolver.resolve_toolset(toolset)

        mock_provider.read_json.assert_not_called()
        assert result.tools == [disabled_ref]
        assert result.tools[0].override == {"deployment": {"name": "never-applied"}}
