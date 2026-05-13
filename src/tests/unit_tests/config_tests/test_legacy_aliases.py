"""
Pin the legacy-alias behavior introduced when `DialDeploymentConfig.name` was
renamed to `deployment_id` and `DialMCPToolSet.dial_id` was renamed to
`deployment_id`.

The aliases must keep working at two layers:
- Pydantic runtime validation (so existing manifests still load).
- The published JSON schema (so DIAL Core's config validator still accepts
  manifests using the legacy keys).
"""

import pytest
from pydantic import ValidationError

from quickapp.common.dial_schema import DialJSONSchemaExtensions
from quickapp.config.dial_deployment import DialDeploymentConfig
from quickapp.config.toolsets.dial_mcp import DialMCPToolSet


class TestDialDeploymentConfigLegacyAlias:
    def test_accepts_canonical_deployment_id(self):
        cfg = DialDeploymentConfig.model_validate({"deployment_id": "gpt-4"})
        assert cfg.deployment_id == "gpt-4"

    def test_accepts_legacy_name(self):
        cfg = DialDeploymentConfig.model_validate({"name": "gpt-4"})
        assert cfg.deployment_id == "gpt-4"

    def test_rejects_when_neither_present(self):
        with pytest.raises(ValidationError):
            DialDeploymentConfig.model_validate({})

    def test_schema_publishes_both_keys(self):
        schema = DialDeploymentConfig.model_json_schema()
        properties = schema["properties"]

        assert "deployment_id" in properties
        assert properties["deployment_id"].get(DialJSONSchemaExtensions.RESOURCE) is True

        assert "name" in properties
        assert properties["name"].get("deprecated") is True

    def test_schema_uses_anyOf_for_required(self):
        schema = DialDeploymentConfig.model_json_schema()
        assert "deployment_id" not in schema.get("required", [])
        assert {"required": ["deployment_id"]} in schema["anyOf"]
        assert {"required": ["name"]} in schema["anyOf"]


class TestDialMCPToolSetLegacyAlias:
    def test_accepts_canonical_deployment_id(self):
        cfg = DialMCPToolSet.model_validate(
            {"type": "dial-mcp", "deployment_id": "toolsets/public/x"}
        )
        assert cfg.deployment_id == "toolsets/public/x"

    def test_accepts_legacy_dial_id(self):
        cfg = DialMCPToolSet.model_validate({"type": "dial-mcp", "dial_id": "toolsets/public/x"})
        assert cfg.deployment_id == "toolsets/public/x"

    def test_rejects_when_neither_present(self):
        with pytest.raises(ValidationError):
            DialMCPToolSet.model_validate({"type": "dial-mcp"})

    def test_schema_publishes_both_keys(self):
        schema = DialMCPToolSet.model_json_schema()
        properties = schema["properties"]

        assert "deployment_id" in properties
        assert properties["deployment_id"].get(DialJSONSchemaExtensions.RESOURCE) is True

        assert "dial_id" in properties
        assert properties["dial_id"].get("deprecated") is True

    def test_schema_uses_anyOf_for_required(self):
        schema = DialMCPToolSet.model_json_schema()
        assert "deployment_id" not in schema.get("required", [])
        assert {"required": ["deployment_id"]} in schema["anyOf"]
        assert {"required": ["dial_id"]} in schema["anyOf"]
