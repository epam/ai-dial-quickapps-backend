from pydantic import BaseModel, ConfigDict, Field
from pydantic.fields import FieldInfo
from pydantic_settings import BaseSettings


class ToolDiscoverySettings(BaseSettings):
    min_tools_for_deferral: int = Field(
        default=5,
        ge=1,
        description="Minimum toolset size for deferral to apply deployment-wide.",
        alias="MIN_TOOLS_FOR_DEFERRAL",
    )


def _min_tools_for_deferral_field() -> FieldInfo:
    description = (
        "Minimum number of tools in a toolset for deferral to apply. "
        "Toolsets with fewer tools than this threshold are promoted to eager loading "
        "even when deferred=true, avoiding discovery overhead for small toolsets. "
        "Default: 5 (or the value of MIN_TOOLS_FOR_DEFERRAL env var)"
    )
    return Field(  # type: ignore[return-value]
        default_factory=lambda: ToolDiscoverySettings().min_tools_for_deferral,
        json_schema_extra={"default": 5},
        ge=1,
        description=description,
    )


class ToolDiscoveryConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    enabled: bool = Field(
        default=False,
        description="Enable dynamic tool discovery. When true, toolsets with deferred=true are withheld from the initial LLM payload and surfaced via the tool_search meta-tool.",
    )
    service_model: str | None = Field(
        default=None,
        description=(
            "DIAL deployment used for the anonymous routing call inside tool_search. "
            "When omitted, falls back to the orchestrator's own deployment."
        ),
    )
    min_tools_for_deferral: int = _min_tools_for_deferral_field()  # type: ignore[assignment]
