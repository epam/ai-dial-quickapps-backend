"""Config surface of the parameters a `deployment-tool` forwards to its deployment."""

import pytest
from pydantic import ValidationError

from quickapp.common.base_config import LegacyAliasModel
from quickapp.config.dial_deployment import DialDeploymentParameters, DialDeploymentToolConfig


class TestStaticTools:
    def test_accepts_static_function(self):
        cfg = DialDeploymentToolConfig.model_validate(
            {
                "name": "gemini-3.5-flash",
                "parameters": {
                    "tools": [
                        {"type": "static_function", "static_function": {"name": "web_search"}}
                    ]
                },
            }
        )

        assert cfg.deployment_id == "gemini-3.5-flash"
        assert cfg.parameters.tools is not None
        assert cfg.parameters.tools[0].static_function.name == "web_search"

    def test_legacy_name_alias_survives_subclassing(self):
        """The tool-scoped config keeps `deployment_id`'s legacy `name` alias."""
        assert issubclass(DialDeploymentToolConfig, LegacyAliasModel)
        cfg = DialDeploymentToolConfig.model_validate({"name": "gpt-4"})
        assert cfg.deployment_id == "gpt-4"

    def test_keeps_provider_specific_keys(self):
        """`extra="allow"` mirrors the SDK model, so unknown keys survive validation."""
        cfg = DialDeploymentToolConfig.model_validate(
            {
                "deployment_id": "gemini-3.5-flash",
                "parameters": {
                    "tools": [
                        {
                            "type": "static_function",
                            "static_function": {"name": "web_search", "threshold": 0.3},
                        }
                    ]
                },
            }
        )

        dumped = cfg.parameters.model_dump(exclude_none=True)
        assert dumped["tools"][0]["static_function"]["threshold"] == 0.3

    def test_rejects_client_side_function_tool(self):
        """A `function` tool would come back as tool calls nobody executes."""
        with pytest.raises(ValidationError):
            DialDeploymentToolConfig.model_validate(
                {
                    "deployment_id": "gpt-4",
                    "parameters": {"tools": [{"type": "function", "function": {"name": "search"}}]},
                }
            )

    def test_tools_are_not_offered_to_the_orchestrator(self):
        """The orchestrator builds its own tools list, so the base parameters have no `tools`."""
        assert "tools" not in DialDeploymentParameters.model_fields


class TestReasoningEffort:
    @pytest.mark.parametrize("effort", ["none", "minimal", "low", "medium", "high"])
    def test_accepts_dial_contract_values(self, effort: str):
        cfg = DialDeploymentToolConfig.model_validate(
            {"deployment_id": "gpt-5", "parameters": {"reasoning_effort": effort}}
        )
        assert cfg.parameters.reasoning_effort == effort

    def test_rejects_value_outside_the_contract(self):
        """`xhigh` is an OpenAI-only value; DIAL deployments reject it."""
        with pytest.raises(ValidationError):
            DialDeploymentToolConfig.model_validate(
                {"deployment_id": "gpt-5", "parameters": {"reasoning_effort": "xhigh"}}
            )
