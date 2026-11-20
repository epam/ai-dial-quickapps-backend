import re

from pydantic import BaseModel, Field, field_validator

# HTTP header-name token characters without "*", so wildcards are rejected explicitly.
_HEADER_NAME = re.compile(r"^x-[0-9a-z!#$%&'+.^_`|~-]+$")

FORWARDED_HEADERS_DESCRIPTION = (
    "Names of the `X-*` request headers this toolset receives. Names are case-insensitive, "
    "must start with `x-` and must not contain wildcards. When unset, a toolset inside the "
    "DIAL contour (DIAL deployments, DIAL apps, DIAL MCP, MCP servers on the DIAL origin) "
    "receives every `X-*` request header and an external toolset (REST API, MCP servers on "
    "other origins) receives none. When set, exactly the listed headers are sent, and `[]` "
    "sends none."
)


class ForwardedHeadersMixin(BaseModel):
    forwarded_headers: list[str] | None = Field(
        default=None, description=FORWARDED_HEADERS_DESCRIPTION
    )

    @field_validator("forwarded_headers")
    @classmethod
    def _normalize_forwarded_headers(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        normalized: list[str] = []
        for name in value:
            lowered = name.strip().lower()
            if "*" in lowered:
                raise ValueError(f"'{name}': wildcards are not supported in forwarded_headers")
            if not _HEADER_NAME.match(lowered):
                raise ValueError(
                    f"'{name}': only X-* header names are allowed in forwarded_headers"
                )
            if lowered not in normalized:
                normalized.append(lowered)
        return normalized
