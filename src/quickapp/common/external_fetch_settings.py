from typing import Any

from pydantic import Field, field_validator
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
    host_allowlist: list[str] | None = Field(
        default=None,
        description=(
            "Optional comma-separated list of host patterns the operator permits for "
            "external URL fetches. When unset, no admin-level host restriction. "
            "Patterns: exact host (`example.com`) or `*.example.com` for any subdomain. "
            "Per-app builder lists can narrow but never expand this set."
        ),
        alias="EXTERNAL_URL_FETCH_HOST_ALLOWLIST",
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

    @field_validator("host_allowlist", mode="before")
    @classmethod
    def _split_csv(cls, v: Any) -> Any:
        if v is None or isinstance(v, list):
            return v
        if not isinstance(v, str):
            return v
        parts = [p.strip() for p in v.split(",") if p.strip()]
        return parts or None
