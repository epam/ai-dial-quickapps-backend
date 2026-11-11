from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.fields import FieldInfo
from pydantic_settings import BaseSettings, SettingsConfigDict


class ToolDiscoverySettings(BaseSettings):
    model_config = SettingsConfigDict()

    min_tools_for_deferral: int = Field(
        default=10,
        ge=1,
        description="Minimum toolset size for deferral to apply deployment-wide.",
        alias="MIN_TOOLS_FOR_DEFERRAL",
    )


def _min_tools_for_deferral_field() -> FieldInfo:
    description = (
        "Minimum number of tools in a toolset for deferral to apply. "
        "Toolsets with fewer tools than this threshold are promoted to eager loading "
        "even when deferred=true, avoiding discovery overhead for small toolsets. "
        "Default: 10 (or the value of MIN_TOOLS_FOR_DEFERRAL env var)"
    )
    return Field(  # type: ignore[return-value]
        default_factory=lambda: ToolDiscoverySettings().min_tools_for_deferral,
        json_schema_extra={"default": 10},
        ge=1,
        description=description,
    )


class BaseSearchStrategyConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    top_k: int = Field(
        default=10,
        ge=1,
        description="Maximum number of tools returned by one internal_tool_search call.",
    )
    score_threshold: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description=(
            "Minimum relevance score (0..1, reported by the routing model) for a pick to be "
            "kept. Picks scored lower are dropped."
        ),
    )


class PlainSearchStrategyConfig(BaseSearchStrategyConfig):
    type: Literal["plain"] = Field(
        default="plain",
        description=(
            "One routing call over the whole deferred tool catalog. "
            "Cheapest to set up, cost grows with the catalog size."
        ),
    )


class WindowSearchStrategyConfig(BaseSearchStrategyConfig):
    type: Literal["window"] = Field(
        default="window",
        description=(
            "The catalog is split into windows that are searched in parallel, then a final "
            "routing call filters the union of the candidates. Best recall on large catalogs, "
            "reads the whole catalog on every search."
        ),
    )
    window_size_chars: int = Field(
        default=40000,
        ge=1000,
        description="Maximum size of one window, in characters of the rendered catalog text.",
    )
    per_window_top_k: int = Field(
        default=3,
        ge=1,
        description="Maximum number of candidates taken from one window before the final filter.",
    )


class HierarchySearchStrategyConfig(BaseSearchStrategyConfig):
    type: Literal["hierarchy"] = Field(
        default="hierarchy",
        description=(
            "Two routing calls: the first picks toolsets from their descriptions, the second "
            "picks tools among the tools of the chosen toolsets. Cheapest on large catalogs, "
            "recall is limited by the toolset choice. score_threshold applies to both calls."
        ),
    )
    toolset_top_k: int = Field(
        default=3,
        ge=1,
        description="Maximum number of toolsets chosen by the first call.",
    )


SearchStrategyConfig = Annotated[
    PlainSearchStrategyConfig | WindowSearchStrategyConfig | HierarchySearchStrategyConfig,
    Field(discriminator="type"),
]


class ToolDiscoveryConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    enabled: bool = Field(
        default=False,
        description="Enable dynamic tool discovery. When true, toolsets with deferred=true are withheld from the initial LLM payload and surfaced via the internal_tool_search meta-tool.",
    )
    service_model: str | None = Field(
        default=None,
        description=(
            "DIAL deployment used for the anonymous routing call inside internal_tool_search. "
            "Required when `enabled` is true. "
            "It must support structured output (`response_format` with a JSON schema)."
        ),
    )
    min_tools_for_deferral: int = _min_tools_for_deferral_field()  # type: ignore[assignment]
    strategy: SearchStrategyConfig = Field(
        default_factory=PlainSearchStrategyConfig,
        description="How internal_tool_search finds tools in the deferred catalog: plain, window or hierarchy.",
    )

    @model_validator(mode="after")
    def _require_service_model_when_enabled(self) -> Self:
        if self.enabled and not self.service_model:
            raise ValueError("service_model is required when tool_discovery is enabled")
        return self
