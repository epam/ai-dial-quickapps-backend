from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ExternalFetchSettings(BaseSettings):
    """Operator-level settings for the external URL fetch egress surface."""

    model_config = SettingsConfigDict()

    allow: bool = Field(
        default=False,
        description=(
            "Admin cap on external URL fetching. When false, no app may fetch "
            "external URLs regardless of its manifest."
        ),
        alias="ALLOW_EXTERNAL_URL_FETCH",
    )
    max_redirects: int = Field(
        default=5,
        description=(
            "Maximum number of HTTP redirects to follow on an external fetch. "
            "Each hop is SSRF-checked. Hard ceiling of 10."
        ),
        alias="EXTERNAL_URL_FETCH_MAX_REDIRECTS",
        ge=0,
        le=10,
    )
    connect_timeout_seconds: float = Field(
        default=5.0,
        description="TCP connect timeout (in seconds) for external URL fetches.",
        alias="EXTERNAL_URL_FETCH_CONNECT_TIMEOUT_SECONDS",
        gt=0,
    )
