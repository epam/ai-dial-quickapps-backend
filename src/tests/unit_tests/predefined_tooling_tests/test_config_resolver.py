import json
from copy import deepcopy
from unittest.mock import MagicMock

import pytest

from quickapp.common.exceptions import ConfigResolutionException
from quickapp.config.predefined_content_provider import (
    ContentType,
    PredefinedContentProvider,
    PredefinedSettings,
)
from quickapp.config.prompt import PredefinedSystemPromptConfig
from quickapp.config.tools.deployment import DialDeploymentTool
from quickapp.config.tools.predefined import PredefinedTool
from quickapp.config.toolsets.deployment import DeploymentToolSet
from quickapp.config.toolsets.predefined import PredefinedToolSet
from quickapp.predefined_tooling import PredefinedConfigResolver
from quickapp.predefined_tooling._predefined_tooling_context import _PredefinedToolingContext


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
def context() -> _PredefinedToolingContext:
    return _PredefinedToolingContext()


@pytest.fixture
def context_provider(context: _PredefinedToolingContext) -> MagicMock:
    provider = MagicMock()
    provider.get.return_value = context
    return provider


@pytest.fixture
def resolver(mock_provider: MagicMock, context_provider: MagicMock) -> PredefinedConfigResolver:
    return PredefinedConfigResolver(mock_provider, context_provider)


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
    """Group B — `PredefinedConfigResolver` applies the override patch before validation."""

    def test_resolve_tool_with_no_override_passes_template_through(
        self, resolver: PredefinedConfigResolver, mock_provider: MagicMock
    ):
        mock_provider.read_json.return_value = _minimal_deployment_tool_template()
        result = resolver.resolve_tool(PredefinedTool(template_name="dial_rag"))
        assert isinstance(result, DialDeploymentTool)
        assert result.deployment.deployment_id == "dial-rag"
        mock_provider.read_json.assert_called_once_with(ContentType.TOOL, "dial_rag")

    def test_resolve_tool_applies_deployment_name_swap(
        self, resolver: PredefinedConfigResolver, mock_provider: MagicMock
    ):
        mock_provider.read_json.return_value = _minimal_deployment_tool_template()
        result = resolver.resolve_tool(
            PredefinedTool(
                template_name="dial_rag",
                override={"deployment": {"name": "hr-rag-prod"}},
            )
        )
        assert isinstance(result, DialDeploymentTool)
        assert result.deployment.deployment_id == "hr-rag-prod"

    def test_resolve_tool_applies_function_description_revision(
        self, resolver: PredefinedConfigResolver, mock_provider: MagicMock
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
        assert result.deployment.deployment_id == "dial-rag"

    def test_resolve_tool_does_not_mutate_template(
        self, resolver: PredefinedConfigResolver, mock_provider: MagicMock
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
        self, resolver: PredefinedConfigResolver, mock_provider: MagicMock
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
        self, resolver: PredefinedConfigResolver, mock_provider: MagicMock
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
        self, resolver: PredefinedConfigResolver, mock_provider: MagicMock
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
        self, resolver: PredefinedConfigResolver, mock_provider: MagicMock
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
        self, resolver: PredefinedConfigResolver, mock_provider: MagicMock
    ):
        mock_provider.read_json.return_value = _minimal_deployment_tool_template()
        with pytest.raises(ConfigResolutionException) as excinfo:
            # `deployment.name` (legacy alias for `deployment_id`) must be a string;
            # passing an int triggers pydantic validation after the merge.
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
        self, resolver: PredefinedConfigResolver, mock_provider: MagicMock
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
        self, resolver: PredefinedConfigResolver, mock_provider: MagicMock
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


class TestResolveConfigSystemPromptFailFast:
    """Group F — system-prompt resolution still aborts the request: the exception
    is recorded on `_PredefinedToolingContext` and re-raised so the caller can
    short-circuit. (Tool/toolset failures are skip-and-record; see Group G.)"""

    def test_system_prompt_failure_appends_exception_to_context_and_reraises(
        self,
        resolver: PredefinedConfigResolver,
        context: _PredefinedToolingContext,
    ):
        raised = ConfigResolutionException(
            message="prompt missing",
            template_name="anthropic_prompt",
        )

        raw_config = MagicMock()
        raw_config.orchestrator.system_prompt = PredefinedSystemPromptConfig(
            template="anthropic_prompt"
        )
        raw_config.tool_sets = []

        def _raise(_template_type, _name):
            raise raised

        resolver.read_template_content = _raise  # type: ignore[method-assign]

        with pytest.raises(ConfigResolutionException) as excinfo:
            resolver.resolve_config(raw_config)

        assert excinfo.value is raised
        assert context.exceptions == [raised]


class TestResolveConfigPartialTolerance:
    """Group G — per-tool and per-toolset failures are skip-and-record: the
    failing item is dropped from the resolved config, the exception is appended
    to `_PredefinedToolingContext`, and peers still resolve."""

    def test_bad_tool_override_drops_tool_records_exception_peers_resolve(
        self,
        resolver: PredefinedConfigResolver,
        mock_provider: MagicMock,
        context: _PredefinedToolingContext,
    ):
        good_template = _minimal_deployment_tool_template()

        def _read_json(_content_type, name):
            if name == "bad_tool":
                # Force a validation failure post-merge (override is fine; the
                # template returned here breaks pydantic validation).
                return {"type": "deployment-tool", "deployment": {}}  # missing 'name'
            return good_template

        mock_provider.read_json.side_effect = _read_json

        toolset = DeploymentToolSet(
            name="chat-hub",
            tools=[
                PredefinedTool(template_name="dial_rag"),
                PredefinedTool(template_name="bad_tool"),
                PredefinedTool(template_name="web_search"),
            ],
        )
        result = resolver.resolve_toolset(toolset)

        assert isinstance(result, DeploymentToolSet)
        resolved_names = [
            t.deployment.deployment_id for t in result.tools if isinstance(t, DialDeploymentTool)
        ]
        assert resolved_names == ["dial-rag", "dial-rag"]
        assert len(result.tools) == 2
        assert len(context.exceptions) == 1
        assert context.exceptions[0].template_name == "bad_tool"

    def test_bad_toolset_override_drops_toolset_peers_resolve(
        self,
        resolver: PredefinedConfigResolver,
        mock_provider: MagicMock,
        context: _PredefinedToolingContext,
    ):
        good_toolset = _minimal_deployment_toolset_template()

        def _read_json(_content_type, name):
            if name == "broken":
                return {"type": "dial-deployment"}  # missing required 'name'
            return good_toolset

        mock_provider.read_json.side_effect = _read_json

        raw_config = MagicMock()
        raw_config.orchestrator.system_prompt = MagicMock(spec=object)
        raw_config.tool_sets = [
            PredefinedToolSet(template_name="chathub"),
            PredefinedToolSet(template_name="broken"),
        ]

        result = resolver.resolve_config(raw_config)

        assert len(result.tool_sets) == 1
        assert isinstance(result.tool_sets[0], DeploymentToolSet)
        assert result.tool_sets[0].name == "chat-hub"
        assert len(context.exceptions) == 1
        assert context.exceptions[0].template_name == "broken"

    def test_resolve_config_succeeds_with_no_failures(
        self,
        resolver: PredefinedConfigResolver,
        mock_provider: MagicMock,
        context: _PredefinedToolingContext,
    ):
        mock_provider.read_json.return_value = _minimal_deployment_toolset_template()

        raw_config = MagicMock()
        raw_config.orchestrator.system_prompt = MagicMock(spec=object)
        raw_config.tool_sets = [PredefinedToolSet(template_name="chathub")]

        result = resolver.resolve_config(raw_config)

        assert len(result.tool_sets) == 1
        assert context.exceptions == []


class TestGetDefaultConfigurationResolved:
    """``get_default_configuration`` expands predefined toolsets and predefined tools."""

    @staticmethod
    def _resolver_with_extra_default(tmp_path) -> PredefinedConfigResolver:
        settings = PredefinedSettings(extra_paths=[str(tmp_path)])
        provider = PredefinedContentProvider(settings)
        context = _PredefinedToolingContext()
        ctx_provider = MagicMock()
        ctx_provider.get.return_value = context
        return PredefinedConfigResolver(provider, ctx_provider)

    def test_expands_predefined_toolset(self, tmp_path):
        (tmp_path / "default_configuration.json").write_text(
            '{"tool_sets": [{"type": "predefined", "template_name": "weather"}]}',
            encoding="utf-8",
        )
        resolver = self._resolver_with_extra_default(tmp_path)
        cfg = resolver.get_default_configuration()
        assert len(cfg["tool_sets"]) == 1
        assert cfg["tool_sets"][0]["type"] == "rest-api"
        assert cfg["tool_sets"][0]["name"] == "Weather rest-api toolset"

    def test_expands_predefined_tools_in_deployment_toolset(self, tmp_path):
        tool_sets = [
            {
                "name": "sample",
                "type": "dial-deployment",
                "tools": [{"type": "predefined-tool", "template_name": "dial_rag"}],
            }
        ]
        (tmp_path / "default_configuration.json").write_text(
            json.dumps({"tool_sets": tool_sets}),
            encoding="utf-8",
        )
        resolver = self._resolver_with_extra_default(tmp_path)
        cfg = resolver.get_default_configuration()
        assert len(cfg["tool_sets"]) == 1
        assert cfg["tool_sets"][0]["type"] == "dial-deployment"
        tools = cfg["tool_sets"][0]["tools"]
        assert len(tools) == 1
        assert tools[0]["type"] == "deployment-tool"

    def test_invalid_tool_sets_type_left_unchanged(self, tmp_path, caplog):
        (tmp_path / "default_configuration.json").write_text(
            '{"tool_sets": "broken", "contexts": []}',
            encoding="utf-8",
        )
        resolver = self._resolver_with_extra_default(tmp_path)
        with caplog.at_level("WARNING"):
            cfg = resolver.get_default_configuration()
        assert cfg["tool_sets"] == "broken"
        assert cfg["contexts"] == []

    def test_does_not_mutate_provider_cache(self, tmp_path):
        (tmp_path / "default_configuration.json").write_text(
            '{"tool_sets": [{"type": "predefined", "template_name": "weather"}]}',
            encoding="utf-8",
        )
        resolver = self._resolver_with_extra_default(tmp_path)
        provider = resolver._provider
        raw_tool_sets = provider.get_default_configuration()["tool_sets"]
        assert raw_tool_sets[0]["type"] == "predefined"

        resolver.get_default_configuration()
        resolver.get_default_configuration()

        assert provider.get_default_configuration()["tool_sets"] == raw_tool_sets

    def test_skips_unknown_predefined_toolset(self, tmp_path, caplog):
        (tmp_path / "default_configuration.json").write_text(
            '{"tool_sets": [{"type": "predefined", "template_name": "no_such_toolset"}]}',
            encoding="utf-8",
        )
        resolver = self._resolver_with_extra_default(tmp_path)
        with caplog.at_level("WARNING"):
            cfg = resolver.get_default_configuration()
        assert cfg["tool_sets"] == []
        assert any("Skipping toolset" in r.message for r in caplog.records)
