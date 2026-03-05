from typing import Any

from quickapp.config.tools.base import (
    ConfigurableSchemaArray,
    ConfigurableSchemaObject,
    ConfigurableSchemaSimpleType,
    JsonTypeEnum,
)


class JsonSchemaConverter:
    """Utility class for converting JSON schema dictionaries to ConfigurableSchema objects."""

    @staticmethod
    def _normalize_type(type_field: Any) -> tuple[str | None, bool]:
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
    def _resolve_ref(ref: str, root_schema: dict[str, Any]) -> dict[str, Any]:
        """
        Resolve an internal JSON Pointer ref like '#/$defs/Name' or '#/definitions/Name'
        by traversing the root_schema. Returns the referenced dictionary.
        """
        if not ref.startswith('#/'):
            raise ValueError(f"Only local refs are supported in this converter: {ref!r}")
        pointer = ref[2:].split('/')  # remove leading '#/'
        node: Any = root_schema
        for token in pointer:
            # JSON Pointer uses ~1 for '/' and ~0 for '~' (not expected here but handle minimally)
            token = token.replace('~1', '/').replace('~0', '~')
            if isinstance(node, dict) and token in node:
                node = node[token]
            else:
                raise KeyError(f"Could not resolve ref {ref!r} at token {token!r}")
        if not isinstance(node, dict):
            raise ValueError(f"Referenced ref {ref!r} does not point to an object")
        return node

    @staticmethod
    def _pick_variant_from_anyof(
        variants: list[dict[str, Any]], root_schema: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Pick the most relevant variant from anyOf/oneOf:
        - prefer a non-null typed variant
        - resolve $ref variants
        - fallback to the first variant
        """
        for v in variants:
            if v.get("type") == "null":
                continue
            # if it's a ref, try to resolve and return resolved (prefer resolved non-null)
            if "$ref" in v:
                try:
                    resolved = JsonSchemaConverter._resolve_ref(v["$ref"], root_schema)
                    # if resolved is not null, return it
                    if resolved.get("type") != "null":
                        return {**resolved, **{k: vv for k, vv in v.items() if k != "$ref"}}
                except Exception:
                    # fall through to treat v as-is
                    return v
            # otherwise return the first non-null typed variant
            if v.get("type") and v.get("type") != "null":
                return v
        # fallback: return first variant (could be null)
        return variants[0]

    @staticmethod
    def _build_schema_from_definition(
        def_dict: dict[str, Any], name: str | None = None, root_schema: dict[str, Any] | None = None
    ) -> Any:
        """
        Build and return a ConfigurableSchema* instance from a single property/items definition.
        This centralizes the handling for simple types, objects and arrays (including nested arrays).
        """
        # If there's a $ref, resolve it against root_schema (if provided).
        if "$ref" in def_dict:
            if root_schema is None:
                raise ValueError("Root schema is required to resolve $ref")
            resolved = JsonSchemaConverter._resolve_ref(def_dict["$ref"], root_schema)
            # Merge resolved with local overrides (local keys take precedence)
            merged = {**resolved, **{k: v for k, v in def_dict.items() if k != "$ref"}}
            def_dict = merged

        # Handle anyOf / oneOf by selecting a representative variant
        if "anyOf" in def_dict or "oneOf" in def_dict:
            variants = def_dict.get("anyOf") or def_dict.get("oneOf")
            if not isinstance(variants, list) or not variants:
                raise ValueError("anyOf/oneOf must be a non-empty list")
            picked = JsonSchemaConverter._pick_variant_from_anyof(variants, root_schema or {})
            # Merge picked with def_dict to preserve top-level default/description etc.
            merged = {
                **picked,
                **{k: v for k, v in def_dict.items() if k not in ("anyOf", "oneOf")},
            }
            def_dict = merged

        raw_type = def_dict.get("type")
        prop_type, is_nullable = JsonSchemaConverter._normalize_type(raw_type)

        description = def_dict.get("description")
        default_value = def_dict.get("default")
        enum_values = def_dict.get("enum")

        # If type is not specified but there are properties, treat as object
        if prop_type is None and "properties" in def_dict:
            prop_type = "object"

        if prop_type is None:
            prop_type = "string"

        if prop_type in ["string", "number", "integer", "boolean"]:
            # ConfigurableSchemaSimpleType doesn't track nullable explicitly;
            # default_value may already be None when schema allowed null.
            return ConfigurableSchemaSimpleType(
                type=getattr(JsonTypeEnum, prop_type),
                description=description,
                enum=enum_values,
                default=default_value,
            )
        elif prop_type == "object":
            # For nested objects, pass the original root_schema so nested refs can be resolved
            nested_properties = JsonSchemaConverter.convert_schema_to_properties(
                def_dict, root_schema=root_schema or def_dict
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
            # recursively build items schema (handles array of arrays, objects, simple types)
            items_schema = JsonSchemaConverter._build_schema_from_definition(
                items_def, name=name, root_schema=root_schema
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
    def convert_schema_to_properties(
        schema_dict: dict[str, Any], root_schema: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """
        Convert a JSON schema dictionary to ConfigurableSchema* properties.

        Args:
            schema_dict: The JSON schema dictionary containing properties definition
            root_schema: optional root schema used to resolve internal $ref pointers.
                         If not provided, schema_dict is used as root.

        Returns:
            Dictionary of converted properties compatible with OpenAiToolFunctionParameters
        """
        properties: dict[str, Any] = {}

        # Preserve the original root for resolving internal refs
        original_root = root_schema or schema_dict

        # Resolve top-level $ref if present
        if "$ref" in schema_dict:
            resolved = JsonSchemaConverter._resolve_ref(schema_dict["$ref"], original_root)
            # Merge resolved with local overrides (local keys take precedence)
            schema_dict = {**resolved, **{k: v for k, v in schema_dict.items() if k != "$ref"}}

        # Handle top-level anyOf/oneOf
        if "anyOf" in schema_dict or "oneOf" in schema_dict:
            variants = schema_dict.get("anyOf") or schema_dict.get("oneOf")
            if not isinstance(variants, list) or not variants:
                raise ValueError("anyOf/oneOf must be a non-empty list")
            picked = JsonSchemaConverter._pick_variant_from_anyof(variants, original_root)
            schema_dict = {
                **picked,
                **{k: v for k, v in schema_dict.items() if k not in ("anyOf", "oneOf")},
            }

        schema_properties = schema_dict.get("properties", {})

        for prop_name, prop_def in schema_properties.items():
            properties[prop_name] = JsonSchemaConverter._build_schema_from_definition(
                prop_def, name=prop_name, root_schema=original_root
            )

        return properties
