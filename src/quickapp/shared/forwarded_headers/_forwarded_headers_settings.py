from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ForwardedHeadersSettings(BaseSettings):
    """Operator-level settings for forwarding X-* request headers to toolsets."""

    model_config = SettingsConfigDict()

    forward_all_to_external: bool = Field(
        default=False,
        description=(
            "Deprecated migration switch. When true, an external toolset (REST API, MCP on a "
            "non-DIAL origin) that sets no `forwarded_headers` receives every X-* request "
            "header, as before. A toolset that sets `forwarded_headers` is unaffected."
        ),
        alias="FORWARD_ALL_X_HEADERS_TO_EXTERNAL_TOOLSETS",
    )
