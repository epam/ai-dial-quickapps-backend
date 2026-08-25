from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ProxySettings(BaseSettings):
    model_config = SettingsConfigDict()

    language_header: str = Field(
        default="accept-language",
        description=(
            "Name of the HTTP request header that carries the locale for UI display. "
            "Resolved value is used for stage name localization."
        ),
        alias="PROXY_LANGUAGE_HEADER",
    )
