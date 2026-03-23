import pytest

from quickapp.common.json_schema_converter import JsonSchemaConverter
from quickapp.config.tools.base import (
    ConfigurableSchemaArray,
    ConfigurableSchemaObject,
    ConfigurableSchemaSimpleType,
    JsonTypeEnum,
)


class TestSimpleTypes:
    def test_string_property(self):
        schema = {
            "type": "object",
            "properties": {"name": {"type": "string", "description": "A name"}},
        }
        result = JsonSchemaConverter.convert_schema_to_properties(schema)
        assert "name" in result
        prop = result["name"]
        assert isinstance(prop, ConfigurableSchemaSimpleType)
        assert prop.type == JsonTypeEnum.string
        assert prop.description == "A name"

    def test_number_property(self):
        schema = {"type": "object", "properties": {"value": {"type": "number"}}}
        result = JsonSchemaConverter.convert_schema_to_properties(schema)
        assert isinstance(result["value"], ConfigurableSchemaSimpleType)
        assert result["value"].type == JsonTypeEnum.number

    def test_integer_property(self):
        schema = {"type": "object", "properties": {"count": {"type": "integer"}}}
        result = JsonSchemaConverter.convert_schema_to_properties(schema)
        assert isinstance(result["count"], ConfigurableSchemaSimpleType)
        assert result["count"].type == JsonTypeEnum.integer

    def test_boolean_property(self):
        schema = {"type": "object", "properties": {"flag": {"type": "boolean"}}}
        result = JsonSchemaConverter.convert_schema_to_properties(schema)
        assert isinstance(result["flag"], ConfigurableSchemaSimpleType)
        assert result["flag"].type == JsonTypeEnum.boolean

    def test_enum_values(self):
        schema = {
            "type": "object",
            "properties": {"color": {"type": "string", "enum": ["red", "green", "blue"]}},
        }
        result = JsonSchemaConverter.convert_schema_to_properties(schema)
        prop = result["color"]
        assert isinstance(prop, ConfigurableSchemaSimpleType)
        assert prop.enum == ["red", "green", "blue"]

    def test_default_value(self):
        schema = {
            "type": "object",
            "properties": {"name": {"type": "string", "default": "hello"}},
        }
        result = JsonSchemaConverter.convert_schema_to_properties(schema)
        assert result["name"].default == "hello"


class TestMissingType:
    def test_missing_type_defaults_to_string(self):
        schema = {"type": "object", "properties": {"unknown": {}}}
        result = JsonSchemaConverter.convert_schema_to_properties(schema)
        assert isinstance(result["unknown"], ConfigurableSchemaSimpleType)
        assert result["unknown"].type == JsonTypeEnum.string

    def test_missing_type_with_properties_defaults_to_object(self):
        schema = {
            "type": "object",
            "properties": {"nested": {"properties": {"inner": {"type": "string"}}}},
        }
        result = JsonSchemaConverter.convert_schema_to_properties(schema)
        assert isinstance(result["nested"], ConfigurableSchemaObject)
        assert result["nested"].type == JsonTypeEnum.object


class TestNullableTypes:
    def test_nullable_type_list(self):
        schema = {
            "type": "object",
            "properties": {"name": {"type": ["string", "null"]}},
        }
        result = JsonSchemaConverter.convert_schema_to_properties(schema)
        prop = result["name"]
        assert isinstance(prop, ConfigurableSchemaSimpleType)
        assert prop.type == JsonTypeEnum.string

    def test_nullable_type_list_integer(self):
        schema = {
            "type": "object",
            "properties": {"count": {"type": ["integer", "null"]}},
        }
        result = JsonSchemaConverter.convert_schema_to_properties(schema)
        assert result["count"].type == JsonTypeEnum.integer


class TestObjectType:
    def test_nested_object(self):
        schema = {
            "type": "object",
            "properties": {
                "config": {
                    "type": "object",
                    "description": "Config object",
                    "properties": {
                        "key": {"type": "string"},
                        "value": {"type": "integer"},
                    },
                    "required": ["key"],
                }
            },
        }
        result = JsonSchemaConverter.convert_schema_to_properties(schema)
        config = result["config"]
        assert isinstance(config, ConfigurableSchemaObject)
        assert config.type == JsonTypeEnum.object
        assert config.description == "Config object"
        assert config.required == ["key"]
        assert "key" in config.properties
        assert "value" in config.properties
        assert isinstance(config.properties["key"], ConfigurableSchemaSimpleType)


class TestArrayType:
    def test_array_of_strings(self):
        schema = {
            "type": "object",
            "properties": {
                "tags": {
                    "type": "array",
                    "description": "Tags",
                    "items": {"type": "string"},
                }
            },
        }
        result = JsonSchemaConverter.convert_schema_to_properties(schema)
        tags = result["tags"]
        assert isinstance(tags, ConfigurableSchemaArray)
        assert tags.type == JsonTypeEnum.array
        assert tags.description == "Tags"
        assert isinstance(tags.items, ConfigurableSchemaSimpleType)
        assert tags.items.type == JsonTypeEnum.string

    def test_array_of_objects(self):
        schema = {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "description": "Items",
                    "items": {
                        "type": "object",
                        "properties": {"id": {"type": "integer"}},
                        "description": "An item",
                    },
                }
            },
        }
        result = JsonSchemaConverter.convert_schema_to_properties(schema)
        arr = result["items"]
        assert isinstance(arr, ConfigurableSchemaArray)
        assert isinstance(arr.items, ConfigurableSchemaObject)
        assert "id" in arr.items.properties

    def test_nested_array(self):
        schema = {
            "type": "object",
            "properties": {
                "matrix": {
                    "type": "array",
                    "description": "Matrix",
                    "items": {
                        "type": "array",
                        "description": "Row",
                        "items": {"type": "number"},
                    },
                }
            },
        }
        result = JsonSchemaConverter.convert_schema_to_properties(schema)
        matrix = result["matrix"]
        assert isinstance(matrix, ConfigurableSchemaArray)
        assert isinstance(matrix.items, ConfigurableSchemaArray)
        assert isinstance(matrix.items.items, ConfigurableSchemaSimpleType)
        assert matrix.items.items.type == JsonTypeEnum.number


class TestRefResolution:
    """Tests that verify the converter resolves $ref pointers."""

    def test_ref_in_property(self):
        schema = {
            "type": "object",
            "properties": {"addr": {"$ref": "#/$defs/Address"}},
            "$defs": {
                "Address": {
                    "type": "object",
                    "description": "Address",
                    "properties": {"city": {"type": "string"}},
                }
            },
        }
        result = JsonSchemaConverter.convert_schema_to_properties(schema)
        addr = result["addr"]
        assert isinstance(addr, ConfigurableSchemaObject)
        assert "city" in addr.properties

    def test_ref_with_sibling_override(self):
        schema = {
            "type": "object",
            "properties": {
                "addr": {
                    "$ref": "#/$defs/Address",
                    "description": "Overridden desc",
                }
            },
            "$defs": {
                "Address": {
                    "type": "object",
                    "description": "Original desc",
                    "properties": {"city": {"type": "string"}},
                }
            },
        }
        result = JsonSchemaConverter.convert_schema_to_properties(schema)
        addr = result["addr"]
        assert isinstance(addr, ConfigurableSchemaObject)
        assert addr.description == "Overridden desc"

    def test_deep_property_path_ref(self):
        """$ref pointing into properties tree (not $defs), as seen in MS Graph API schemas."""
        days_enum = ["sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"]
        schema = {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "object",
                    "description": "Pattern",
                    "properties": {
                        "daysOfWeek": {
                            "type": "array",
                            "items": {
                                "anyOf": [
                                    {"type": "string", "enum": days_enum},
                                    {
                                        "type": "object",
                                        "properties": {},
                                        "additionalProperties": True,
                                    },
                                ]
                            },
                            "description": "Days of week",
                        },
                        "firstDayOfWeek": {
                            "$ref": "#/properties/pattern/properties/daysOfWeek/items/anyOf/0"
                        },
                    },
                }
            },
        }
        result = JsonSchemaConverter.convert_schema_to_properties(schema)
        pattern = result["pattern"]
        assert isinstance(pattern, ConfigurableSchemaObject)

        first_day = pattern.properties["firstDayOfWeek"]
        assert isinstance(first_day, ConfigurableSchemaSimpleType)
        assert first_day.type == JsonTypeEnum.string
        assert first_day.enum == days_enum

        days = pattern.properties["daysOfWeek"]
        assert isinstance(days, ConfigurableSchemaArray)

    def test_unresolvable_ref_raises(self):
        """Leftover $ref after dereferencing raises ValueError."""
        schema = {
            "type": "object",
            "properties": {"bad": {"$ref": "#/$defs/DoesNotExist"}},
        }
        with pytest.raises(ValueError, match="Unresolved \\$ref"):
            JsonSchemaConverter.convert_schema_to_properties(schema)

    def test_top_level_ref_resolved(self):
        """Top-level $ref is resolved by the converter."""
        schema = {
            "$ref": "#/$defs/Root",
            "$defs": {
                "Root": {
                    "type": "object",
                    "properties": {"x": {"type": "string"}},
                }
            },
        }
        result = JsonSchemaConverter.convert_schema_to_properties(schema)
        assert "x" in result
        assert isinstance(result["x"], ConfigurableSchemaSimpleType)


class TestAnyOfOneOf:
    def test_anyof_picks_non_null(self):
        schema = {
            "type": "object",
            "properties": {"name": {"anyOf": [{"type": "string"}, {"type": "null"}]}},
        }
        result = JsonSchemaConverter.convert_schema_to_properties(schema)
        prop = result["name"]
        assert isinstance(prop, ConfigurableSchemaSimpleType)
        assert prop.type == JsonTypeEnum.string

    def test_oneof_picks_non_null(self):
        schema = {
            "type": "object",
            "properties": {"value": {"oneOf": [{"type": "null"}, {"type": "integer"}]}},
        }
        result = JsonSchemaConverter.convert_schema_to_properties(schema)
        prop = result["value"]
        assert isinstance(prop, ConfigurableSchemaSimpleType)
        assert prop.type == JsonTypeEnum.integer

    def test_anyof_with_ref(self):
        schema = {
            "type": "object",
            "properties": {
                "item": {
                    "anyOf": [
                        {"$ref": "#/$defs/Item"},
                        {"type": "null"},
                    ]
                }
            },
            "$defs": {
                "Item": {
                    "type": "object",
                    "description": "An item",
                    "properties": {"id": {"type": "integer"}},
                }
            },
        }
        result = JsonSchemaConverter.convert_schema_to_properties(schema)
        item = result["item"]
        assert isinstance(item, ConfigurableSchemaObject)
        assert "id" in item.properties

    def test_anyof_preserves_description(self):
        schema = {
            "type": "object",
            "properties": {
                "name": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "description": "A name field",
                }
            },
        }
        result = JsonSchemaConverter.convert_schema_to_properties(schema)
        assert result["name"].description == "A name field"

    def test_top_level_anyof(self):
        schema = {
            "anyOf": [
                {
                    "type": "object",
                    "properties": {"x": {"type": "string"}},
                },
                {"type": "null"},
            ]
        }
        result = JsonSchemaConverter.convert_schema_to_properties(schema)
        assert "x" in result


class TestCircularRefs:
    """Tests that verify the converter handles circular $ref schemas without recursion.

    dereference_refs creates a copy of the referenced dict on the first encounter,
    so the circular Python reference only appears at the *second* occurrence.
    The first copy is fully converted; the second is truncated to an opaque object.
    """

    def test_direct_self_reference(self):
        """A property whose $ref resolves back to itself (A -> A cycle)."""
        schema = {
            "type": "object",
            "properties": {
                "node": {
                    "type": "object",
                    "properties": {
                        "value": {"type": "integer"},
                        "self_ref": {"$ref": "#/properties/node"},
                    },
                },
            },
        }
        result = JsonSchemaConverter.convert_schema_to_properties(schema)
        node = result["node"]
        assert isinstance(node, ConfigurableSchemaObject)
        assert isinstance(node.properties["value"], ConfigurableSchemaSimpleType)

        # First copy is fully resolved
        self_ref = node.properties["self_ref"]
        assert isinstance(self_ref, ConfigurableSchemaObject)
        assert isinstance(self_ref.properties["value"], ConfigurableSchemaSimpleType)

        # Second occurrence is truncated (circular Python reference detected)
        nested_ref = self_ref.properties["self_ref"]
        assert isinstance(nested_ref, ConfigurableSchemaObject)
        assert nested_ref.properties == {}

    def test_indirect_circular_reference(self):
        """A -> B -> A cycle (mirrors OneNote parentNotebook <-> sectionGroups pattern)."""
        schema = {
            "type": "object",
            "properties": {
                "notebook": {
                    "type": "object",
                    "description": "A notebook",
                    "properties": {
                        "name": {"type": "string"},
                        "sections": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "title": {"type": "string"},
                                    "parentNotebook": {"$ref": "#/properties/notebook"},
                                },
                            },
                        },
                    },
                },
            },
        }
        result = JsonSchemaConverter.convert_schema_to_properties(schema)
        notebook = result["notebook"]
        assert isinstance(notebook, ConfigurableSchemaObject)
        assert isinstance(notebook.properties["name"], ConfigurableSchemaSimpleType)

        sections = notebook.properties["sections"]
        assert isinstance(sections, ConfigurableSchemaArray)
        assert isinstance(sections.items, ConfigurableSchemaObject)

        section_props = sections.items.properties
        assert isinstance(section_props["title"], ConfigurableSchemaSimpleType)

        # First copy of notebook is fully resolved
        parent_nb = section_props["parentNotebook"]
        assert isinstance(parent_nb, ConfigurableSchemaObject)
        assert isinstance(parent_nb.properties["name"], ConfigurableSchemaSimpleType)

        # Second occurrence (inside the copy) is truncated
        nested_sections = parent_nb.properties["sections"]
        assert isinstance(nested_sections, ConfigurableSchemaArray)
        nested_parent = nested_sections.items.properties["parentNotebook"]
        assert isinstance(nested_parent, ConfigurableSchemaObject)
        assert nested_parent.properties == {}

    def test_non_circular_siblings_converted_normally(self):
        """Non-circular properties alongside circular ones are converted normally."""
        schema = {
            "type": "object",
            "properties": {
                "node": {
                    "type": "object",
                    "properties": {
                        "value": {"type": "integer", "description": "Node value"},
                        "parent": {"$ref": "#/properties/node"},
                    },
                },
                "label": {"type": "string", "description": "A label"},
            },
        }
        result = JsonSchemaConverter.convert_schema_to_properties(schema)
        # Top-level non-circular property
        assert isinstance(result["label"], ConfigurableSchemaSimpleType)
        assert result["label"].description == "A label"

        # Nested non-circular property
        node = result["node"]
        assert isinstance(node, ConfigurableSchemaObject)
        assert isinstance(node.properties["value"], ConfigurableSchemaSimpleType)
        assert node.properties["value"].description == "Node value"

        # First copy is fully resolved; second is truncated
        parent = node.properties["parent"]
        assert isinstance(parent, ConfigurableSchemaObject)
        assert isinstance(parent.properties["value"], ConfigurableSchemaSimpleType)
        assert parent.properties["parent"].properties == {}


class TestUnsupportedType:
    def test_unsupported_type_raises(self):
        schema = {
            "type": "object",
            "properties": {"bad": {"type": "unknown_type"}},
        }
        with pytest.raises(ValueError, match="Unsupported property type"):
            JsonSchemaConverter.convert_schema_to_properties(schema)


class TestMultipleProperties:
    def test_multiple_properties_converted(self):
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Name"},
                "age": {"type": "integer", "description": "Age"},
                "active": {"type": "boolean"},
            },
        }
        result = JsonSchemaConverter.convert_schema_to_properties(schema)
        assert len(result) == 3
        assert result["name"].type == JsonTypeEnum.string
        assert result["age"].type == JsonTypeEnum.integer
        assert result["active"].type == JsonTypeEnum.boolean

    def test_empty_properties(self):
        schema = {"type": "object", "properties": {}}
        result = JsonSchemaConverter.convert_schema_to_properties(schema)
        assert result == {}
