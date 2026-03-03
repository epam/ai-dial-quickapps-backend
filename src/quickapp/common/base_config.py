from collections import deque
from copy import deepcopy
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, Field
from pydantic.fields import FieldInfo

_DIAL_SCHEMA_URL = "https://dial.epam.com/application_type_schemas/schema#"
_DIAL_ID_PREFIX = "https://mydial.epam.com/custom_application_schemas/"


def _collect_defs_references(schema: Any) -> set[str]:
    """Return the set of $defs keys referenced in *schema*."""
    seen: set[str] = set()
    q: deque = deque([schema])

    while q:
        node = q.popleft()
        if isinstance(node, dict):
            ref = node.get("$ref")
            if ref and ref.startswith("#/$defs/"):
                seen.add(ref.split("/")[-1])
            q.extend(node.values())
        elif isinstance(node, list):
            q.extend(node)

    return seen


def _flatten_root_properties(schema: dict) -> dict:
    """
    1. Inline root-level refs.
    2. Drop any `$defs` entries that are no longer referenced.
    """
    schema = deepcopy(schema)
    defs = schema.get("$defs", {})

    # ---------- 1 · inline only first-level refs ----------
    for prop_name, prop_schema in list(schema.get("properties", {}).items()):
        ref = prop_schema.get("$ref")
        if ref and ref.startswith("#/$defs/"):
            key = ref.split("/")[-1]
            if key in defs:  # safety check
                extras = {k: v for k, v in prop_schema.items() if k != "$ref"}
                inlined = deepcopy(defs[key])
                inlined.update(extras)
                schema["properties"][prop_name] = inlined

    # ---------- 2 · prune unreferenced $defs ----------
    still_used = _collect_defs_references(schema)
    for key in list(defs):
        if key not in still_used:
            defs.pop(key)
    if not defs:
        schema.pop("$defs", None)

    return schema


# Type alias for dial:propertyKind values
DialPropertyKind = Literal["client", "server"]


def _dial_config_field(
    default: Any = ..., *, property_kind: DialPropertyKind = "server", **kwargs
) -> FieldInfo:
    """
    Create a Pydantic Field with DIAL-specific metadata.

    Args:
        default: Default value for the field
        property_kind: DIAL property kind - "client" or "server" (default: "server")
        property_order: Order of the property in the default configuration UI (default: None, will be auto-assigned)
        **kwargs: Other Pydantic Field parameters

    Returns:
        Pydantic Field with DIAL metadata
    """
    json_schema_extra = kwargs.get("json_schema_extra", {})
    if isinstance(json_schema_extra, dict):
        json_schema_extra["dial:propertyKind"] = property_kind
    else:
        # If json_schema_extra is a callable, wrap it
        original_extra = json_schema_extra

        def new_extra(schema):
            if callable(original_extra):
                original_extra(schema)
            schema["dial:propertyKind"] = property_kind

        json_schema_extra = new_extra

    kwargs["json_schema_extra"] = json_schema_extra
    return Field(default, **kwargs)


def _dial_resource_config_field(default: Any = ..., **kwargs) -> FieldInfo:
    """
    Create a Pydantic Field to mark DIAL resources.

    Args:
        default: Default value for the field
        **kwargs: Other Pydantic Field parameters

    Returns:
        Pydantic Field with mark of DIAL resources
    """
    json_schema_extra = kwargs.get("json_schema_extra", {})
    if isinstance(json_schema_extra, dict):
        json_schema_extra["dial:resource"] = True
    else:
        # If json_schema_extra is a callable, wrap it
        original_extra = json_schema_extra

        def new_extra(schema):
            if callable(original_extra):
                original_extra(schema)
            schema["dial:resource"] = True

        json_schema_extra = new_extra

    kwargs["json_schema_extra"] = json_schema_extra
    return Field(default, **kwargs)


def _dial_file_config_field(default: Any = ..., **kwargs) -> FieldInfo:
    """
    Create a Pydantic Field for DIAL file URLs with DIAL-specific metadata.

    Args:
        default: Default value for the field
        **kwargs: Other Pydantic Field parameters

    Returns:
        Pydantic Field with DIAL metadata and file URL format
    """
    json_schema_extra = kwargs.get("json_schema_extra", {})
    if isinstance(json_schema_extra, dict):
        json_schema_extra["dial:file"] = True
        json_schema_extra["format"] = "dial-file-encoded"
    else:
        # If json_schema_extra is a callable, wrap it
        original_extra = json_schema_extra

        def new_extra(schema):
            if callable(original_extra):
                original_extra(schema)
            schema["dial:file"] = True
            schema["format"] = "dial-file-encoded"

        json_schema_extra = new_extra

    kwargs["json_schema_extra"] = json_schema_extra
    return Field(default, **kwargs)


class BaseApplicationTypeConfig(BaseModel):
    """
    Base class for configuration of schema-rich applications in DIAL.
    """

    # Class variables for DIAL schema configuration
    _dial_schema_id: ClassVar[str]
    _dial_application_type_display_name: ClassVar[str]
    _dial_append_application_properties_header: ClassVar[bool] = False

    __schema_attributes_order: ClassVar[list[str]] = [
        "type",
        "$id",
        "$schema",
        "dial:applicationTypeDisplayName",
        "dial:appendApplicationPropertiesHeader",
        "title",
        "$defs",
        "properties",
        "required",
    ]

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

        if not hasattr(cls, '_dial_schema_id') or cls._dial_schema_id is None:
            raise TypeError(
                f"Class {cls.__name__} must define '_dial_schema_id' class variable. "
                f"Example: _dial_schema_id = 'myapp'"
            )

        if (
            not hasattr(cls, '_dial_application_type_display_name')
            or cls._dial_application_type_display_name is None
        ):
            raise TypeError(
                f"Class {cls.__name__} must define '_dial_application_type_display_name' class variable. "
                f"Example: _dial_application_type_display_name = 'My Application'"
            )

    @classmethod
    def _get_property_kind(cls, field_info: FieldInfo) -> DialPropertyKind:
        """
        Extract dial:propertyKind from field metadata.

        Args:
            field_info: Pydantic FieldInfo object

        Returns:
            "client" or "server" (default: "server")
        """
        if field_info.json_schema_extra:
            if isinstance(field_info.json_schema_extra, dict):
                value = field_info.json_schema_extra.get("dial:propertyKind", "server")
                if value not in ("client", "server"):
                    raise ValueError(
                        f"Invalid dial:propertyKind value: {value}. "
                        "Must be 'client' or 'server'."
                    )
                return value  # type: ignore[return-value]
            # If it's a callable, we can't easily extract it here
            # This will be handled when the schema is generated

        return "server"

    # Overrides schema generation to include "dial:meta" for root properties and flatten them (no $defs usage).
    @classmethod
    def model_json_schema(cls, include_dial_fields=True, *args, **kwargs):
        schema = super().model_json_schema(*args, **kwargs)
        schema = _flatten_root_properties(schema)

        properties = schema.get("properties", {})
        model_fields = cls.model_fields

        for idx, (prop_name, prop_schema) in enumerate(properties.items()):
            # Get property kind from field metadata or schema
            property_kind = "server"
            if "dial:propertyKind" in prop_schema:
                property_kind = prop_schema.pop("dial:propertyKind")
            elif prop_name in model_fields:
                field_info = model_fields[prop_name]
                property_kind = cls._get_property_kind(field_info)

            prop_schema["dial:meta"] = {
                "dial:propertyKind": property_kind,
                "dial:propertyOrder": idx + 1,
            }

        # Add DIAL-specific root properties
        if include_dial_fields:
            schema["$id"] = f"{_DIAL_ID_PREFIX}{cls._dial_schema_id}"
            schema["$schema"] = _DIAL_SCHEMA_URL
            schema["dial:applicationTypeDisplayName"] = cls._dial_application_type_display_name
            schema["dial:appendApplicationPropertiesHeader"] = (
                cls._dial_append_application_properties_header
            )

        # order the schema attributes and append all other attributes
        ordered_schema = {
            key: schema[key] for key in cls.__schema_attributes_order if key in schema
        }
        for key in schema:
            if key not in cls.__schema_attributes_order:
                ordered_schema[key] = schema[key]

        return ordered_schema


# public aliases for the dial config fields
DialConfigField = _dial_config_field
DialFileConfigField = _dial_file_config_field
DialResourceConfigField = _dial_resource_config_field
