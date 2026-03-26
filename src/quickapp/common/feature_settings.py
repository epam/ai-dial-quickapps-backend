"""Feature gating settings. Lives in common to avoid circular imports."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class FeatureSettings(BaseSettings):
    """Controls preview feature availability deployment-wide."""

    model_config = SettingsConfigDict()

    enable_preview_features: bool = Field(
        default=False,
        description="Enable preview features across the deployment",
        alias="ENABLE_PREVIEW_FEATURES",
    )
