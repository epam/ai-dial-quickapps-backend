from collections import deque
from copy import deepcopy
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, Field
from pydantic.fields import FieldInfo

from quickapp.common.dial_schema import DialJSONSchemaExtensions
from quickapp.common.feature_settings import FeatureSettings

_DIAL_SCHEMA_URL = "https://dial.epam.com/application_type_schemas/schema#"
_DIAL_ID_PREFIX = "https://mydial.epam.com/custom_application_schemas/"

_PREVIEW_MARKER = "x-preview"


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
        json_schema_extra[DialJSONSchemaExtensions.PROPERTY_KIND] = property_kind
    else:
        # If json_schema_extra is a callable, wrap it
        original_extra = json_schema_extra

        def new_extra(schema):
            if callable(original_extra):
                original_extra(schema)
            schema[DialJSONSchemaExtensions.PROPERTY_KIND] = property_kind

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
        json_schema_extra[DialJSONSchemaExtensions.RESOURCE] = True
    else:
        # If json_schema_extra is a callable, wrap it
        original_extra = json_schema_extra

        def new_extra(schema):
            if callable(original_extra):
                original_extra(schema)
            schema[DialJSONSchemaExtensions.RESOURCE] = True

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
        json_schema_extra[DialJSONSchemaExtensions.FILE] = True
        json_schema_extra["format"] = "dial-file-encoded"
    else:
        # If json_schema_extra is a callable, wrap it
        original_extra = json_schema_extra

        def new_extra(schema):
            if callable(original_extra):
                original_extra(schema)
            schema[DialJSONSchemaExtensions.FILE] = True
            schema["format"] = "dial-file-encoded"

        json_schema_extra = new_extra

    kwargs["json_schema_extra"] = json_schema_extra
    return Field(default, **kwargs)


def _preview_field(default=None, **kwargs) -> FieldInfo:
    """
    Create a Pydantic Field marked as a preview feature.

    Preview fields are stripped from the JSON schema and nullified at runtime
    when ENABLE_PREVIEW_FEATURES is not set.

    The field type must be ``T | None`` so the runtime can deactivate it by
    setting the value to ``None``.  Use either ``default=None`` (field is off
    by default) or ``default_factory=SomeModel`` (field is on by default but
    can still be nullified when preview features are disabled).

    Args:
        default: Must be None when no ``default_factory`` is provided.
        **kwargs: Other Pydantic Field parameters (including ``default_factory``).

    Returns:
        Pydantic Field with preview marker.
    """
    has_factory = "default_factory" in kwargs
    if default is not None and not has_factory:
        raise TypeError(
            "PreviewField requires default=None (preview fields must be nullable "
            "so they can be deactivated at runtime). "
            "Use default_factory=... if the feature should be enabled by default."
        )
    json_schema_extra = kwargs.get("json_schema_extra", {})
    if isinstance(json_schema_extra, dict):
        json_schema_extra[_PREVIEW_MARKER] = True
    else:
        original_extra = json_schema_extra

        def new_extra(schema):
            if callable(original_extra):
                original_extra(schema)
            schema[_PREVIEW_MARKER] = True

        json_schema_extra = new_extra
    kwargs["json_schema_extra"] = json_schema_extra
    if has_factory:
        return Field(**kwargs)
    return Field(default, **kwargs)


def has_preview_marker(field_info: FieldInfo) -> bool:
    """Check whether a field is marked as a preview feature."""
    extra = field_info.json_schema_extra
    if extra is None:
        return False
    if isinstance(extra, dict):
        return bool(extra.get(_PREVIEW_MARKER, False))
    # Callable case: invoke on a temp dict to inspect the marker.
    tmp: dict[str, Any] = {}
    extra(tmp)
    return bool(tmp.get(_PREVIEW_MARKER, False))


def _strip_preview_properties(obj: dict) -> None:
    """Remove preview-marked properties and clean up required list in-place."""
    properties = obj.get("properties")
    if not properties:
        return
    to_remove = [name for name, prop in properties.items() if prop.get(_PREVIEW_MARKER)]
    for name in to_remove:
        del properties[name]
    required = obj.get("required")
    if required:
        obj["required"] = [r for r in required if r not in to_remove]
        if not obj["required"]:
            del obj["required"]


def _strip_preview_fields(schema: dict) -> dict:
    """Remove preview-marked properties from a JSON schema dict."""
    schema = deepcopy(schema)

    # Strip at root level
    _strip_preview_properties(schema)

    # Strip within $defs
    for definition in schema.get("$defs", {}).values():
        _strip_preview_properties(definition)

    # Prune unreferenced $defs
    defs = schema.get("$defs", {})
    if defs:
        still_used = _collect_defs_references(schema)
        for key in list(defs):
            if key not in still_used:
                defs.pop(key)
        if not defs:
            schema.pop("$defs", None)

    return schema


class BaseApplicationTypeConfig(BaseModel):
    """
    Base class for configuration of schema-rich applications in DIAL.
    """

    # Class variables for DIAL schema configuration
    _dial_schema_id: ClassVar[str]
    _dial_application_type_display_name: ClassVar[str]
    _dial_append_application_properties_header: ClassVar[bool] = False
    _dial_assistant_attachments_in_request_supported: ClassVar[bool] = True

    _schema_attributes_order: ClassVar[list[str]] = [
        DialJSONSchemaExtensions.DISPLAY_NAME,
        DialJSONSchemaExtensions.APPEND_APP_PROPERTIES_HEADER,
        DialJSONSchemaExtensions.ASSISTANT_ATTACHMENTS_IN_REQUEST,
        "type",
        "$id",
        "$schema",
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
                value = field_info.json_schema_extra.get(
                    DialJSONSchemaExtensions.PROPERTY_KIND, "server"
                )
                if value not in ("client", "server"):
                    raise ValueError(
                        f"Invalid {DialJSONSchemaExtensions.PROPERTY_KIND} value: {value}. "
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

        if not FeatureSettings().enable_preview_features:
            schema = _strip_preview_fields(schema)

        properties = schema.get("properties", {})
        model_fields = cls.model_fields

        for idx, (prop_name, prop_schema) in enumerate(properties.items()):
            # Get property kind from field metadata or schema
            property_kind = "server"
            if DialJSONSchemaExtensions.PROPERTY_KIND in prop_schema:
                property_kind = prop_schema.pop(DialJSONSchemaExtensions.PROPERTY_KIND)
            elif prop_name in model_fields:
                field_info = model_fields[prop_name]
                property_kind = cls._get_property_kind(field_info)

            prop_schema[DialJSONSchemaExtensions.META] = {
                DialJSONSchemaExtensions.PROPERTY_KIND: property_kind,
                DialJSONSchemaExtensions.PROPERTY_ORDER: idx + 1,
            }

        # Add DIAL-specific root properties
        if include_dial_fields:
            schema["$id"] = f"{_DIAL_ID_PREFIX}{cls._dial_schema_id}"
            schema["$schema"] = _DIAL_SCHEMA_URL
            schema[DialJSONSchemaExtensions.DISPLAY_NAME] = cls._dial_application_type_display_name
            schema[DialJSONSchemaExtensions.APPEND_APP_PROPERTIES_HEADER] = (
                cls._dial_append_application_properties_header
            )
            schema[DialJSONSchemaExtensions.ASSISTANT_ATTACHMENTS_IN_REQUEST] = (
                cls._dial_assistant_attachments_in_request_supported
            )

        # order the schema attributes and append all other attributes
        ordered_schema = {key: schema[key] for key in cls._schema_attributes_order if key in schema}
        for key in schema:
            if key not in cls._schema_attributes_order:
                ordered_schema[key] = schema[key]

        return ordered_schema


# public aliases for the dial config fields
DialConfigField = _dial_config_field
DialFileConfigField = _dial_file_config_field
DialResourceConfigField = _dial_resource_config_field
PreviewField = _preview_field
