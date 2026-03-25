import pytest
from pydantic import BaseModel, Field

from quickapp.common.base_config import (
    _PREVIEW_MARKER,
    BaseApplicationTypeConfig,
    PreviewField,
    _has_preview_marker,
    _strip_preview_fields,
)

# ── PreviewField ──────────────────────────────────────────────────────


class TestPreviewField:
    def test_marker_set_in_dict_extra(self):
        class M(BaseModel):
            feat: str | None = PreviewField(description="test")

        field_info = M.model_fields["feat"]
        assert isinstance(field_info.json_schema_extra, dict)
        assert field_info.json_schema_extra[_PREVIEW_MARKER] is True

    def test_default_must_be_none(self):
        with pytest.raises(TypeError, match="PreviewField requires default=None"):
            PreviewField(default="something")

    def test_default_none_accepted(self):
        field = PreviewField(default=None)
        assert field.default is None

    def test_default_omitted_accepted(self):
        field = PreviewField()
        assert field.default is None

    def test_wraps_callable_json_schema_extra(self):
        def custom_extra(schema):
            schema["custom"] = True

        class M(BaseModel):
            feat: str | None = PreviewField(json_schema_extra=custom_extra)

        schema = M.model_json_schema()
        feat_schema = schema["properties"]["feat"]
        assert feat_schema.get(_PREVIEW_MARKER) is True
        assert feat_schema.get("custom") is True

    def test_with_description(self):
        class M(BaseModel):
            feat: str | None = PreviewField(description="A preview feature")

        schema = M.model_json_schema()
        assert schema["properties"]["feat"]["description"] == "A preview feature"

    def test_marker_appears_in_json_schema(self):
        class M(BaseModel):
            feat: str | None = PreviewField()
            stable: str = Field(default="ok")

        schema = M.model_json_schema()
        assert schema["properties"]["feat"].get(_PREVIEW_MARKER) is True
        assert _PREVIEW_MARKER not in schema["properties"]["stable"]


# ── _has_preview_marker ───────────────────────────────────────────────


class TestHasPreviewMarker:
    def test_dict_with_marker(self):
        class M(BaseModel):
            feat: str | None = PreviewField()

        assert _has_preview_marker(M.model_fields["feat"]) is True

    def test_callable_with_marker(self):
        def custom_extra(schema):
            schema["custom"] = True

        class M(BaseModel):
            feat: str | None = PreviewField(json_schema_extra=custom_extra)

        assert _has_preview_marker(M.model_fields["feat"]) is True

    def test_regular_field(self):
        class M(BaseModel):
            stable: str = Field(default="ok")

        assert _has_preview_marker(M.model_fields["stable"]) is False

    def test_none_extra(self):
        class M(BaseModel):
            bare: str

        assert _has_preview_marker(M.model_fields["bare"]) is False


# ── _strip_preview_fields ─────────────────────────────────────────────


class TestStripPreviewFields:
    def test_basic_strip(self):
        schema = {
            "properties": {
                "stable": {"type": "string"},
                "preview": {"type": "string", _PREVIEW_MARKER: True},
            },
            "required": ["stable", "preview"],
        }
        result = _strip_preview_fields(schema)
        assert "stable" in result["properties"]
        assert "preview" not in result["properties"]

    def test_removes_from_required(self):
        schema = {
            "properties": {
                "stable": {"type": "string"},
                "preview": {"type": "string", _PREVIEW_MARKER: True},
            },
            "required": ["stable", "preview"],
        }
        result = _strip_preview_fields(schema)
        assert result["required"] == ["stable"]

    def test_empty_required_removed(self):
        schema = {
            "properties": {
                "preview": {"type": "string", _PREVIEW_MARKER: True},
            },
            "required": ["preview"],
        }
        result = _strip_preview_fields(schema)
        assert "required" not in result

    def test_strips_within_defs(self):
        schema = {
            "properties": {
                "nested": {"$ref": "#/$defs/Nested"},
            },
            "$defs": {
                "Nested": {
                    "properties": {
                        "stable": {"type": "string"},
                        "preview": {"type": "string", _PREVIEW_MARKER: True},
                    },
                    "required": ["stable", "preview"],
                }
            },
        }
        result = _strip_preview_fields(schema)
        nested_def = result["$defs"]["Nested"]
        assert "stable" in nested_def["properties"]
        assert "preview" not in nested_def["properties"]
        assert nested_def["required"] == ["stable"]

    def test_prunes_unreferenced_defs(self):
        schema = {
            "properties": {
                "preview": {"$ref": "#/$defs/PreviewModel", _PREVIEW_MARKER: True},
            },
            "$defs": {
                "PreviewModel": {"type": "object", "properties": {"x": {"type": "string"}}},
            },
        }
        result = _strip_preview_fields(schema)
        assert "$defs" not in result

    def test_preserves_shared_defs(self):
        schema = {
            "properties": {
                "stable": {"$ref": "#/$defs/SharedModel"},
                "preview": {"$ref": "#/$defs/SharedModel", _PREVIEW_MARKER: True},
            },
            "$defs": {
                "SharedModel": {"type": "object"},
            },
        }
        result = _strip_preview_fields(schema)
        assert "SharedModel" in result["$defs"]
        assert "stable" in result["properties"]
        assert "preview" not in result["properties"]

    def test_noop_when_no_preview_fields(self):
        schema = {
            "properties": {
                "a": {"type": "string"},
                "b": {"type": "integer"},
            },
            "required": ["a", "b"],
        }
        result = _strip_preview_fields(schema)
        assert result == schema

    def test_does_not_mutate_original(self):
        schema = {
            "properties": {
                "preview": {"type": "string", _PREVIEW_MARKER: True},
            },
        }
        _strip_preview_fields(schema)
        assert "preview" in schema["properties"]


# ── model_json_schema integration ─────────────────────────────────────


class TestModelJsonSchemaPreviewIntegration:
    def test_preview_field_stripped_when_disabled(self, monkeypatch):
        monkeypatch.delenv("ENABLE_PREVIEW_FEATURES", raising=False)

        class Cfg(BaseApplicationTypeConfig):
            _dial_schema_id = "test"
            _dial_application_type_display_name = "Test"
            stable: str
            preview_feat: str | None = PreviewField(description="preview")

        schema = Cfg.model_json_schema()
        assert "stable" in schema["properties"]
        assert "preview_feat" not in schema["properties"]

    def test_preview_field_present_when_enabled(self, monkeypatch):
        monkeypatch.setenv("ENABLE_PREVIEW_FEATURES", "true")

        class Cfg(BaseApplicationTypeConfig):
            _dial_schema_id = "test"
            _dial_application_type_display_name = "Test"
            stable: str
            preview_feat: str | None = PreviewField(description="preview")

        schema = Cfg.model_json_schema()
        assert "stable" in schema["properties"]
        assert "preview_feat" in schema["properties"]
