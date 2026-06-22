from typing import Any

from fastmcp.utilities.json_schema import dereference_refs
from jsonref import JsonRefError, replace_refs  # type: ignore[import-untyped]

from quickapp.config.tools.base import (
    ConfigurableSchemaArray,
    ConfigurableSchemaObject,
    ConfigurableSchemaSimpleType,
    JsonTypeEnum,
)

_ConfigurableSchema = (
    ConfigurableSchemaSimpleType | ConfigurableSchemaObject | ConfigurableSchemaArray
)


class JsonSchemaConverter:
    """Utility class for converting JSON schema dictionaries to ConfigurableSchema objects.

    Handles $ref resolution internally via fastmcp dereference_refs(), falling back
    to jsonref.replace_refs() for schemas with circular references.
    """

    @staticmethod
    def _contains_ref(obj: Any) -> bool:
        if isinstance(obj, dict):
            if "$ref" in obj:
                return True
            return any(JsonSchemaConverter._contains_ref(v) for v in obj.values())
        if isinstance(obj, list):
            return any(JsonSchemaConverter._contains_ref(v) for v in obj)
        return False

    @staticmethod
    def _dereference_with_jsonref(schema_dict: dict[str, Any]) -> dict[str, Any]:
        dereferenced = replace_refs(schema_dict, proxies=False, lazy_load=False)
        if not isinstance(dereferenced, dict):
            raise TypeError(f"Expected dict from replace_refs, got {type(dereferenced).__name__}")
        return dereferenced

    @staticmethod
    def _normalize_type(type_field: str | list[str] | None) -> str | None:
        """
        Normalize the 'type' field which can be a str or a list (e.g. ['string', 'null']).
        Returns the primary non-null type, or None if no non-null type is present.
        """
        if isinstance(type_field, list):
            non_null = [t for t in type_field if t != 'null']
            return non_null[0] if non_null else None
        return type_field

    @staticmethod
    def _pick_variant_from_anyof(variants: list[dict[str, Any]]) -> dict[str, Any]:
        """
        Pick the most relevant variant from anyOf/oneOf:
        - prefer a non-null typed variant
        - fallback to the first variant
        """
        for v in variants:
            if v.get("type") == "null":
                continue
            if v.get("type"):
                return v
        return variants[0]

    @staticmethod
    def _build_schema_from_definition(
        def_dict: dict[str, Any],
        name: str | None = None,
        seen: set[int] | None = None,
        allow_circular_expansion: bool = True,
    ) -> _ConfigurableSchema:
        """
        Build and return a ConfigurableSchema* instance from a single property/items definition.
        This centralizes the handling for simple types, objects and arrays (including nested arrays).

        ``seen`` tracks ``id()`` of dicts already on the call stack to break
        circular Python references produced by ``dereference_refs``.
        """
        if "$ref" in def_dict:
            raise ValueError(
                f"Unresolved $ref '{def_dict['$ref']}' in property {name!r}. "
                "Schema must be dereferenced before conversion."
            )

        # Handle anyOf / oneOf by selecting a representative variant
        if "anyOf" in def_dict or "oneOf" in def_dict:
            variants = def_dict.get("anyOf") or def_dict.get("oneOf")
            if not isinstance(variants, list) or not variants:
                raise ValueError("anyOf/oneOf must be a non-empty list")
            picked = JsonSchemaConverter._pick_variant_from_anyof(variants)
            # Merge picked with def_dict to preserve top-level default/description etc.
            merged = {
                **picked,
                **{k: v for k, v in def_dict.items() if k not in ("anyOf", "oneOf")},
            }
            def_dict = merged

        raw_type = def_dict.get("type")
        prop_type = JsonSchemaConverter._normalize_type(raw_type)

        description = def_dict.get("description")
        default_value = def_dict.get("default")
        enum_values = def_dict.get("enum")

        # If type is not specified but there are properties, treat as object
        if prop_type is None and "properties" in def_dict:
            prop_type = "object"

        if prop_type is None:
            prop_type = "string"

        if prop_type in ["string", "number", "integer", "boolean"]:
            return ConfigurableSchemaSimpleType(
                type=getattr(JsonTypeEnum, prop_type),
                description=description,
                enum=enum_values,
                default=default_value,
            )
        elif prop_type == "object":
            nested_properties = JsonSchemaConverter._convert_properties(
                def_dict, seen, allow_circular_expansion
            )
            return ConfigurableSchemaObject(
                type=JsonTypeEnum.object,
                properties=nested_properties,
                description=description or "",
                required=def_dict.get("required"),
                default=default_value,
            )
        elif prop_type == "array":
            items_def = def_dict.get("items", {})
            items_schema = JsonSchemaConverter._build_schema_from_definition(
                items_def,
                name=name,
                seen=seen,
                allow_circular_expansion=allow_circular_expansion,
            )
            return ConfigurableSchemaArray(
                type=JsonTypeEnum.array,
                items=items_schema,
                description=description or "",
                default=default_value,
            )
        else:
            raise ValueError(f"Unsupported property type: {prop_type!r} for property {name!r}")

    @staticmethod
    def _convert_properties(
        schema_dict: dict[str, Any],
        seen: set[int] | None = None,
        allow_circular_expansion: bool = True,
    ) -> dict[str, _ConfigurableSchema]:
        """Internal recursive conversion with cycle detection (no ref resolution)."""
        if seen is None:
            seen = set()

        # Handle top-level anyOf/oneOf
        if "anyOf" in schema_dict or "oneOf" in schema_dict:
            variants = schema_dict.get("anyOf") or schema_dict.get("oneOf")
            if not isinstance(variants, list) or not variants:
                raise ValueError("anyOf/oneOf must be a non-empty list")
            picked = JsonSchemaConverter._pick_variant_from_anyof(variants)
            schema_dict = {
                **picked,
                **{k: v for k, v in schema_dict.items() if k not in ("anyOf", "oneOf")},
            }

        schema_properties = schema_dict.get("properties", {})

        properties: dict[str, _ConfigurableSchema] = {}
        for prop_name, prop_def in schema_properties.items():
            dict_id = id(prop_def)
            if dict_id in seen:
                if allow_circular_expansion:
                    # First re-encounter: expand one more level with a fresh seen
                    # set so the object's own simple properties aren't falsely
                    # flagged as circular. Disable further expansion to prevent
                    # infinite recursion.
                    circular_seen: set[int] = {dict_id}
                    properties[prop_name] = JsonSchemaConverter._build_schema_from_definition(
                        prop_def,
                        name=prop_name,
                        seen=circular_seen,
                        allow_circular_expansion=False,
                    )
                else:
                    # Second re-encounter: truncate to an opaque object
                    properties[prop_name] = ConfigurableSchemaObject(
                        type=JsonTypeEnum.object,
                        properties={},
                        description=prop_def.get("description", ""),
                    )
                continue
            seen.add(dict_id)
            properties[prop_name] = JsonSchemaConverter._build_schema_from_definition(
                prop_def,
                name=prop_name,
                seen=seen,
                allow_circular_expansion=allow_circular_expansion,
            )

        return properties

    @staticmethod
    def convert_schema_to_properties(
        schema_dict: dict[str, Any],
    ) -> dict[str, _ConfigurableSchema]:
        """
        Convert a JSON schema dictionary to ConfigurableSchema* properties.

        Resolves any $ref pointers before conversion. Uses fastmcp's dereference_refs()
        for full resolution with sibling merging, falling back to jsonref.replace_refs()
        for schemas with circular references that cause RecursionError in post-processing.

        Args:
            schema_dict: The JSON schema dictionary containing properties definition

        Returns:
            Dictionary of converted properties compatible with OpenAiToolFunctionParameters
        """
        try:
            schema_dict = dereference_refs(schema_dict)
        except RecursionError:
            # Circular inline $ref can blow the stack in fastmcp post-processing.
            schema_dict = JsonSchemaConverter._dereference_with_jsonref(schema_dict)
        else:
            if JsonSchemaConverter._contains_ref(schema_dict):
                # fastmcp may leave inline circular $ref unresolved; jsonref materializes
                # circular Python dicts that _convert_properties handles via id().
                try:
                    schema_dict = JsonSchemaConverter._dereference_with_jsonref(schema_dict)
                except JsonRefError:
                    pass  # broken refs -> ValueError during conversion

        return JsonSchemaConverter._convert_properties(schema_dict)
