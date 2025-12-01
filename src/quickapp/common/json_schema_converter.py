from typing import Any, Dict, Tuple

from quickapp.config.tools.base import (
    ConfigurableSchemaArray,
    ConfigurableSchemaObject,
    ConfigurableSchemaSimpleType,
    JsonTypeEnum,
)


class JsonSchemaConverter:
    """Utility class for converting JSON schema dictionaries to ConfigurableSchema objects."""

    @staticmethod
    def _normalize_type(type_field: Any) -> Tuple[str | None, bool]:
        """
        Normalize the 'type' field which can be a str or a list (e.g. ['string', 'null']).
        Returns (primary_type_or_None, is_nullable).
        """
        if isinstance(type_field, list):
            is_nullable = 'null' in type_field
            non_null = [t for t in type_field if t != 'null']
            primary = non_null[0] if non_null else None
            return primary, is_nullable
        return (type_field, False) if type_field is not None else (None, False)

    @staticmethod
    def _build_schema_from_definition(def_dict: Dict[str, Any], name: str | None = None) -> Any:
        """
        Build and return a ConfigurableSchema* instance from a single property/items definition.
        This centralizes the handling for simple types, objects and arrays (including nested arrays).
        """
        raw_type = def_dict.get('type')
        prop_type, is_nullable = JsonSchemaConverter._normalize_type(raw_type)

        description = def_dict.get('description')
        default_value = def_dict.get('default')
        enum_values = def_dict.get('enum')

        if prop_type is None:
            prop_type = 'string'

        if prop_type in ['string', 'number', 'integer', 'boolean']:
            return ConfigurableSchemaSimpleType(
                type=getattr(JsonTypeEnum, prop_type),
                description=description,
                enum=enum_values,
                default=default_value,
            )
        elif prop_type == 'object':
            nested_properties = JsonSchemaConverter.convert_schema_to_properties(def_dict)
            return ConfigurableSchemaObject(
                type=JsonTypeEnum.object,
                properties=nested_properties,
                description=description or '',
                required=def_dict.get('required'),
                default=default_value,
            )
        elif prop_type == 'array':
            items_def = def_dict.get('items', {})
            # recursively build items schema (handles array of arrays, objects, simple types)
            items_schema = JsonSchemaConverter._build_schema_from_definition(items_def, name=name)
            return ConfigurableSchemaArray(
                type=JsonTypeEnum.array,
                items=items_schema,
                description=description or '',
                default=default_value,
            )
        else:
            raise ValueError(f"Unsupported property type: {prop_type!r} for property {name!r}")

    @staticmethod
    def convert_schema_to_properties(schema_dict: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convert a JSON schema dictionary to ConfigurableSchema* properties.

        Args:
            schema_dict: The JSON schema dictionary containing properties definition

        Returns:
            Dictionary of converted properties compatible with OpenAiToolFunctionParameters
        """
        properties: Dict[str, Any] = {}
        schema_properties = schema_dict.get('properties', {})

        for prop_name, prop_def in schema_properties.items():
            properties[prop_name] = JsonSchemaConverter._build_schema_from_definition(
                prop_def, name=prop_name
            )

        return properties
