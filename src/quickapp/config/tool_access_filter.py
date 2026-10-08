from pydantic import BaseModel, ConfigDict, Field


class ToolAccessFilterConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    enabled: bool = Field(
        default=False,
        description=(
            "Enable per-user access filtering. When true, the configured DIAL deployment tools, "
            "DIAL app toolsets and `dial-mcp` toolsets are intersected with the models, applications "
            "and toolsets DIAL Core reports as accessible to the calling user (GET /v1/deployment-names), so the model is never offered "
            "a tool the user cannot call. If DIAL Core cannot be queried, all configured tools "
            "are offered (fail-open); DIAL Core still enforces access when a tool is called."
        ),
    )
