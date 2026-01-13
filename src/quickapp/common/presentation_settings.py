from pydantic_settings import BaseSettings

from quickapp.config.utils import bool_env_var


class PresentationSettings(BaseSettings):
    show_usage_statistics: bool = bool_env_var("SHOW_USAGE_STATISTICS", False)
