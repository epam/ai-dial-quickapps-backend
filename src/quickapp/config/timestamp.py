from typing import Literal

from pydantic import BaseModel, field_validator

from quickapp.common.base_config import PreviewField
from quickapp.common.iana_timezones import is_valid_iana_timezone


class ToolCallTimestampConfig(BaseModel):
    injection_strategy: Literal["tool_call"] = "tool_call"
    default_timezone: str | None = PreviewField(  # type: ignore[assignment]
        default=None,
        description=(
            "IANA time zone (e.g. 'Europe/Warsaw') used when the request carries no valid "
            "X-Timezone header. Unset means UTC."
        ),
        json_schema_extra={"examples": ["Europe/Warsaw"]},
    )

    @field_validator("default_timezone", mode="after")
    @classmethod
    def _validate_default_timezone(cls, value: str | None) -> str | None:
        if value is not None and not is_valid_iana_timezone(value):
            raise ValueError(
                f"default_timezone '{value}' is not a known IANA time zone, e.g. 'Europe/Warsaw'"
            )
        return value


# Type alias — currently a single variant.  When a second strategy is added
# (e.g. SystemPromptTimestampConfig), change this to a discriminated union:
#   TimestampConfig = Annotated[
#       ToolCallTimestampConfig | SystemPromptTimestampConfig,
#       Discriminator("injection_strategy"),
#   ]
TimestampConfig = ToolCallTimestampConfig
