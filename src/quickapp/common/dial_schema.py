from enum import StrEnum


class DialJSONSchemaExtensions(StrEnum):
    DISPLAY_NAME = "dial:applicationTypeDisplayName"
    APPEND_APP_PROPERTIES_HEADER = "dial:appendApplicationPropertiesHeader"
    ASSISTANT_ATTACHMENTS_IN_REQUEST = "dial:applicationTypeAssistantAttachmentsInRequestSupported"
    COMPLETION_ENDPOINT = "dial:applicationTypeCompletionEndpoint"
    CONFIGURATION_ENDPOINT = "dial:applicationTypeConfigurationEndpoint"
    TYPE_SCHEMA_ENDPOINT = "dial:applicationTypeSchemaEndpoint"

    META = "dial:meta"
    PROPERTY_KIND = "dial:propertyKind"
    PROPERTY_ORDER = "dial:propertyOrder"
    RESOURCE = "dial:resource"
    FILE = "dial:file"

    DEFAULT_LOCALE = "dial:defaultLocale"
    LOCALIZED = "dial:localized"
    TAB = "dial:tab"
    SECTION = "dial:section"
    WIDGET = "dial:widget"
