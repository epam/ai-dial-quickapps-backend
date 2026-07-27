"""Application schema settings. Lives in common to avoid circular imports."""

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEFAULT_DIAL_ID_PREFIX = "https://mydial.epam.com/custom_application_schemas/"


class SchemaSettings(BaseSettings):
    """Controls the application type schema ``$id`` emitted in generated schemas."""

    model_config = SettingsConfigDict()

    app_schema_id: str | None = Field(
        default=None,
        alias="APP_SCHEMA_ID",
        description=(
            "Full application type schema $id override. When unset, uses the "
            "built-in default (prefix + per-class _dial_schema_id)."
        ),
    )

    @field_validator("app_schema_id", mode="after")
    @classmethod
    def _blank_to_none(cls, value: str | None) -> str | None:
        # BaseSettings returns "" (not None) for an empty/whitespace env value.
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    def resolve_schema_id(self, dial_schema_id: str) -> str:
        """Return ``APP_SCHEMA_ID`` when set, else ``prefix + dial_schema_id``."""
        return self.app_schema_id or f"{_DEFAULT_DIAL_ID_PREFIX}{dial_schema_id}"
