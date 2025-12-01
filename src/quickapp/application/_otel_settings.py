from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class _OtelSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='otel_')

    service_name: str = Field(
        "quickapps", description="The name of the service for OpenTelemetry tracing and metrics"
    )
