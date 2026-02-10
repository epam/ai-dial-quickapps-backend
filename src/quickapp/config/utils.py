import logging
import os

logger = logging.getLogger(__name__)


def bool_env_var(param: str, default: bool) -> bool:
    """Read a boolean env var. Prefer per-module pydantic Settings for app configuration."""
    value = os.getenv(param, str(default)).lower()
    if value not in ["true", "false"]:
        logger.warning("Env variable `%s` has invalid boolean value `%s`", param, value)
    return value == "true"
