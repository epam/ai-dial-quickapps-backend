import logging
import os

logger = logging.getLogger(__name__)


def bool_env_var(param, default):
    value = os.getenv(param, str(default)).lower()
    if value not in ["true", "false"]:
        logger.warning(f"Env variable `{param}` has invalid boolean value `{value}`")
    return value == "true"
