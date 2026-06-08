"""
Pin the legacy-alias behavior introduced when `DialDeploymentConfig.name` was
renamed to `deployment_id` and `DialMCPToolSet.dial_id` was renamed to
`deployment_id`.

The aliases must keep working at three layers:
- Pydantic runtime validation (so existing manifests still load).
- The published JSON schema (so DIAL Core's config validator still accepts
  manifests using the legacy keys).
- DIAL field-level schema markers (`dial:resource`, `dial:file`, `format`)
  must mirror onto the alias so schema-driven tooling that keys off those
  markers (e.g. resource discovery / auto-share) still sees manifests stored
  under the legacy key.
"""

from typing import Annotated

import pytest
from pydantic import ValidationError

from quickapp.common.base_config import (
    DialFileConfigField,
    DialResourceConfigField,
    LegacyAlias,
    LegacyAliasModel,
)
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
        assert properties["name"].get(DialJSONSchemaExtensions.RESOURCE) is True

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
        assert properties["dial_id"].get(DialJSONSchemaExtensions.RESOURCE) is True

    def test_schema_uses_anyOf_for_required(self):
        schema = DialMCPToolSet.model_json_schema()
        assert "deployment_id" not in schema.get("required", [])
        assert {"required": ["deployment_id"]} in schema["anyOf"]
        assert {"required": ["dial_id"]} in schema["anyOf"]


class TestLegacyAliasModelMarkerPropagation:
    """Pin the propagation rule directly against `LegacyAliasModel`, independent
    of any specific production consumer — guards future uses of the helper."""

    def test_file_marker_and_format_propagate_to_alias(self):
        class _FileModel(LegacyAliasModel):
            file_url: Annotated[
                str,
                DialFileConfigField(description="A DIAL file URL."),
                LegacyAlias("file"),
            ]

        schema = _FileModel.model_json_schema()
        properties = schema["properties"]

        assert properties["file_url"].get(DialJSONSchemaExtensions.FILE) is True
        assert properties["file_url"].get("format") == "dial-file-encoded"

        assert properties["file"].get("deprecated") is True
        assert properties["file"].get(DialJSONSchemaExtensions.FILE) is True
        assert properties["file"].get("format") == "dial-file-encoded"

    def test_resource_marker_propagates_to_alias(self):
        class _ResourceModel(LegacyAliasModel):
            deployment_id: Annotated[
                str,
                DialResourceConfigField(description="A DIAL resource id."),
                LegacyAlias("old_name"),
            ]

        schema = _ResourceModel.model_json_schema()
        properties = schema["properties"]

        assert properties["deployment_id"].get(DialJSONSchemaExtensions.RESOURCE) is True
        assert properties["old_name"].get("deprecated") is True
        assert properties["old_name"].get(DialJSONSchemaExtensions.RESOURCE) is True
