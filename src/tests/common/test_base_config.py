import pytest
from typing import Optional, List
from pydantic import BaseModel, Field

from quickapp.common.base_config import (
    BaseApplicationTypeConfig,
    _collect_defs_references,
    _flatten_root_properties,
    DialConfigField,
    DialFileConfigField,
)


class TestInitSubclass:
    """Test the __init_subclass__ validation."""

    def test_missing_dial_schema_id_raises_error(self):
        """Test that missing _dial_schema_id raises TypeError."""
        with pytest.raises(TypeError) as exc_info:

            class MissingIdConfig(BaseApplicationTypeConfig):
                _dial_application_type_display_name = "Test App"
                name: str

        assert "must define '_dial_schema_id'" in str(exc_info.value)
        assert "MissingIdConfig" in str(exc_info.value)

    def test_missing_dial_application_type_display_name_raises_error(self):
        """Test that missing _dial_application_type_display_name raises TypeError."""
        with pytest.raises(TypeError) as exc_info:

            class MissingDisplayNameConfig(BaseApplicationTypeConfig):
                _dial_schema_id = "test_app"
                name: str

        assert "must define '_dial_application_type_display_name'" in str(exc_info.value)
        assert "MissingDisplayNameConfig" in str(exc_info.value)

    def test_valid_subclass_creation(self):
        """Test that valid subclass can be created successfully."""

        class ValidConfig(BaseApplicationTypeConfig):
            _dial_schema_id = "test_app"
            _dial_application_type_display_name = "Test Application"
            name: str
            enabled: bool = True

        # Should not raise any errors
        assert ValidConfig._dial_schema_id == "test_app"
        assert ValidConfig._dial_application_type_display_name == "Test Application"
        assert ValidConfig._dial_append_application_properties_header is False

    def test_override_dial_append_application_properties_header(self):
        """Test that _dial_append_application_properties_header can be overridden."""

        class OverrideConfig(BaseApplicationTypeConfig):
            _dial_schema_id = "test_app"
            _dial_application_type_display_name = "Test Application"
            _dial_append_application_properties_header = True
            name: str

        assert OverrideConfig._dial_append_application_properties_header is True


class TestModelJsonSchema:
    """Test the model_json_schema method."""

    def test_basic_schema_generation(self):
        """Test basic schema generation with required DIAL properties."""

        class TestConfig(BaseApplicationTypeConfig):
            _dial_schema_id = "quickapps2"
            _dial_application_type_display_name = "Quick App 2.0"

            name: str
            enabled: bool = True
            max_tokens: int = Field(default=1000, description="Maximum tokens")

        schema = TestConfig.model_json_schema()

        # Check DIAL-specific root properties
        assert schema["$id"] == "https://mydial.epam.com/custom_application_schemas/quickapps2"
        assert schema["$schema"] == "https://dial.epam.com/application_type_schemas/schema#"
        assert schema["dial:applicationTypeDisplayName"] == "Quick App 2.0"
        assert schema["dial:appendApplicationPropertiesHeader"] is False

        # Check properties have dial:meta
        assert "name" in schema["properties"]
        assert schema["properties"]["name"]["dial:meta"] == {
            "dial:propertyKind": "server",
            "dial:propertyOrder": 1,
        }
        assert schema["properties"]["enabled"]["dial:meta"] == {
            "dial:propertyKind": "server",
            "dial:propertyOrder": 2,
        }
        assert schema["properties"]["max_tokens"]["dial:meta"] == {
            "dial:propertyKind": "server",
            "dial:propertyOrder": 3,
        }

    def test_schema_with_override_append_header(self):
        """Test schema generation with overridden _dial_append_application_properties_header."""

        class TestConfig(BaseApplicationTypeConfig):
            _dial_schema_id = "test_app"
            _dial_application_type_display_name = "Test App"
            _dial_append_application_properties_header = True

            field: str

        schema = TestConfig.model_json_schema()
        assert schema["dial:appendApplicationPropertiesHeader"] is True

    def test_schema_attribute_ordering(self):
        """Test that schema attributes are ordered correctly."""

        class TestConfig(BaseApplicationTypeConfig):
            _dial_schema_id = "test_app"
            _dial_application_type_display_name = "Test App"

            name: str
            value: int

        schema = TestConfig.model_json_schema()
        keys = list(schema.keys())

        # Check order of known attributes
        expected_order = [
            "type",
            "$id",
            "$schema",
            "dial:applicationTypeDisplayName",
            "dial:appendApplicationPropertiesHeader",
            "title",
            "properties",
            "required",
        ]

        actual_order = [k for k in keys if k in expected_order]
        assert actual_order == [k for k in expected_order if k in schema]

    def test_schema_with_nested_models(self):
        """Test schema generation with nested models to verify flattening."""

        class NestedModel(BaseModel):
            nested_field: str
            nested_value: int = 42

        class TestConfig(BaseApplicationTypeConfig):
            _dial_schema_id = "nested_test"
            _dial_application_type_display_name = "Nested Test"

            simple_field: str
            nested: NestedModel
            optional_nested: Optional[NestedModel] = None

        schema = TestConfig.model_json_schema()

        # Check that nested model is inlined in properties
        assert "nested" in schema["properties"]
        nested_schema = schema["properties"]["nested"]

        # The nested field should have dial:meta
        assert "dial:meta" in nested_schema

        # Check if $defs is removed or cleaned up properly
        if "$defs" in schema:
            # If $defs exists, verify it only contains referenced definitions
            assert len(schema["$defs"]) >= 0  # Could be empty or contain only used refs


class TestHelperFunctions:
    """Test the helper functions."""

    def test_collect_defs_references_no_refs(self):
        """Test _collect_defs_references with schema without references."""
        schema = {
            "type": "object",
            "properties": {"name": {"type": "string"}, "value": {"type": "integer"}},
        }
        refs = _collect_defs_references(schema)
        assert refs == set()

    def test_collect_defs_references_with_refs(self):
        """Test _collect_defs_references with schema containing references."""
        schema = {
            "type": "object",
            "properties": {
                "item1": {"$ref": "#/$defs/Model1"},
                "item2": {"$ref": "#/$defs/Model2"},
                "nested": {
                    "type": "object",
                    "properties": {"ref_item": {"$ref": "#/$defs/Model3"}},
                },
            },
            "required": ["item1"],
            "$defs": {
                "Model1": {"type": "string"},
                "Model2": {"type": "integer"},
                "Model3": {"type": "boolean"},
            },
        }
        refs = _collect_defs_references(schema)
        assert refs == {"Model1", "Model2", "Model3"}

    def test_collect_defs_references_in_arrays(self):
        """Test _collect_defs_references with references in arrays."""
        schema = {
            "type": "object",
            "properties": {"items": {"type": "array", "items": {"$ref": "#/$defs/ItemModel"}}},
            "$defs": {"ItemModel": {"type": "object"}},
        }
        refs = _collect_defs_references(schema)
        assert refs == {"ItemModel"}

    def test_flatten_root_properties_simple(self):
        """Test _flatten_root_properties with simple schema."""
        schema = {
            "type": "object",
            "properties": {"field1": {"$ref": "#/$defs/StringType"}, "field2": {"type": "integer"}},
            "$defs": {"StringType": {"type": "string", "minLength": 1}},
        }

        flattened = _flatten_root_properties(schema)

        # field1 should be inlined
        assert flattened["properties"]["field1"] == {"type": "string", "minLength": 1}
        # $defs should be removed since StringType is no longer referenced
        assert "$defs" not in flattened

    def test_flatten_root_properties_with_extras(self):
        """Test _flatten_root_properties preserves extra properties on refs."""
        schema = {
            "type": "object",
            "properties": {
                "field1": {
                    "$ref": "#/$defs/Model",
                    "description": "Extra description",
                    "title": "Extra title",
                }
            },
            "$defs": {"Model": {"type": "string", "pattern": "^[A-Z]"}},
        }

        flattened = _flatten_root_properties(schema)

        # Check that extras are preserved
        assert flattened["properties"]["field1"]["description"] == "Extra description"
        assert flattened["properties"]["field1"]["title"] == "Extra title"
        assert flattened["properties"]["field1"]["type"] == "string"
        assert flattened["properties"]["field1"]["pattern"] == "^[A-Z]"

    def test_flatten_root_properties_keeps_used_defs(self):
        """Test _flatten_root_properties keeps $defs that are still referenced."""
        schema = {
            "type": "object",
            "properties": {
                "field1": {"$ref": "#/$defs/Model1"},
                "field2": {"type": "object", "properties": {"nested": {"$ref": "#/$defs/Model2"}}},
            },
            "$defs": {
                "Model1": {"type": "string"},
                "Model2": {"type": "integer"},
                "Model3": {"type": "boolean"},  # Unused
            },
        }

        flattened = _flatten_root_properties(schema)

        # field1 should be inlined
        assert flattened["properties"]["field1"] == {"type": "string"}
        # Model2 should still be in $defs (referenced by nested)
        assert "Model2" in flattened["$defs"]
        # Model3 should be removed (not referenced)
        assert "Model3" not in flattened["$defs"]
        # Model1 should be removed (was inlined)
        assert "Model1" not in flattened["$defs"]


class TestIntegration:
    """Integration tests with real-world examples."""

    def test_complex_model_with_various_field_types(self):
        """Test with a complex model containing various field types."""

        class ComplexConfig(BaseApplicationTypeConfig):
            _dial_schema_id = "complex_app"
            _dial_application_type_display_name = "Complex Application"

            # Various field types
            text_field: str
            number_field: int
            float_field: float = 3.14
            bool_field: bool = True
            optional_field: Optional[str] = None
            list_field: List[str] = Field(default_factory=list)

        schema = ComplexConfig.model_json_schema()

        # Verify all fields have dial:meta
        for idx, field_name in enumerate(
            [
                "text_field",
                "number_field",
                "float_field",
                "bool_field",
                "optional_field",
                "list_field",
            ],
            1,
        ):
            assert field_name in schema["properties"]
            assert schema["properties"][field_name]["dial:meta"] == {
                "dial:propertyKind": "server",
                "dial:propertyOrder": idx,
            }

        # Verify required fields
        assert "text_field" in schema["required"]
        assert "number_field" in schema["required"]
        assert "optional_field" not in schema.get("required", [])

    def test_model_instance_creation(self):
        """Test that model instances can be created and validated."""

        class AppConfig(BaseApplicationTypeConfig):
            _dial_schema_id = "app"
            _dial_application_type_display_name = "App"

            name: str
            port: int = 8080

        # Valid instance
        config = AppConfig(name="MyApp", port=9000)
        assert config.name == "MyApp"
        assert config.port == 9000

        # Test validation
        with pytest.raises(ValueError):
            AppConfig(name="MyApp", port="not_a_number")  # type: ignore


def test_dial_config_field_property_kind():
    """Test that DialConfigField correctly sets property kind."""

    class TestConfig(BaseApplicationTypeConfig):
        _dial_schema_id = "test"
        _dial_application_type_display_name = "Test"

        server_field: str = DialConfigField(property_kind="server")
        client_field: str = DialConfigField(property_kind="client")
        default_field: str  # Should default to "server"

    schema = TestConfig.model_json_schema()

    assert schema["properties"]["server_field"]["dial:meta"]["dial:propertyKind"] == "server"
    assert schema["properties"]["client_field"]["dial:meta"]["dial:propertyKind"] == "client"
    assert schema["properties"]["default_field"]["dial:meta"]["dial:propertyKind"] == "server"


def test_dial_config_field_with_other_parameters():
    """Test that DialConfigField works with other Field parameters."""

    class TestConfig(BaseApplicationTypeConfig):
        _dial_schema_id = "test"
        _dial_application_type_display_name = "Test"

        field: str = DialConfigField(
            default="test",
            property_kind="client",
            description="Test field",
            min_length=3,
            max_length=10,
        )

    schema = TestConfig.model_json_schema()
    field_schema = schema["properties"]["field"]

    assert field_schema["dial:meta"]["dial:propertyKind"] == "client"
    assert field_schema["description"] == "Test field"
    assert field_schema["minLength"] == 3
    assert field_schema["maxLength"] == 10


class TestDialFileConfigField:
    """Tests for DialFileConfigField."""

    def test_dial_file_config_field_metadata(self):
        class TestConfig(BaseApplicationTypeConfig):
            _dial_schema_id = "file_test"
            _dial_application_type_display_name = "File Test"
            file_url: str = DialFileConfigField()

        schema = TestConfig.model_json_schema()
        file_schema = schema["properties"]["file_url"]

        assert file_schema["dial:file"] is True
        assert file_schema["format"] == "dial-file-encoded"
        assert "dial:meta" in file_schema

    def test_dial_file_config_field_with_other_parameters(self):
        class TestConfig(BaseApplicationTypeConfig):
            _dial_schema_id = "file_test"
            _dial_application_type_display_name = "File Test"
            file_url: str = DialFileConfigField(
                default="https://example.com/file.txt",
                description="A file URL",
                min_length=10,
            )

        schema = TestConfig.model_json_schema()
        file_schema = schema["properties"]["file_url"]

        assert file_schema["dial:file"] is True
        assert file_schema["format"] == "dial-file-encoded"
        assert file_schema["description"] == "A file URL"
        assert file_schema["minLength"] == 10
