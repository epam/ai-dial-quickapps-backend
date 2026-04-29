import copy
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_DISCRIMINATOR_KEY = "type"


def bool_env_var(param: str, default: bool) -> bool:
    """Read a boolean env var. Prefer per-module pydantic Settings for app configuration."""
    value = os.getenv(param, str(default)).lower()
    if value not in ["true", "false"]:
        logger.warning("Env variable `%s` has invalid boolean value `%s`", param, value)
    return value == "true"


class JsonMergePatchError(ValueError):
    """JSON Merge Patch (RFC 7396) could not be applied."""

    def __init__(self, message: str, path: str = ""):
        super().__init__(message)
        self.message = message
        self.path = path


def json_merge_patch(target: Any, patch: Any) -> Any:
    """Apply a JSON Merge Patch (RFC 7396), rejecting any patch that contains
    a `type` discriminator key at any depth.
    """
    _reject_type_discriminator(patch)
    return _do_merge(target, patch)


def _reject_type_discriminator(value: Any, path: str = "") -> None:
    if isinstance(value, dict):
        for key, sub in value.items():
            sub_path = f"{path}/{key}"
            if key == _DISCRIMINATOR_KEY:
                raise JsonMergePatchError(
                    f"'{_DISCRIMINATOR_KEY}' discriminator may not be overridden by a patch",
                    path=sub_path,
                )
            _reject_type_discriminator(sub, sub_path)
    elif isinstance(value, list):
        for idx, sub in enumerate(value):
            _reject_type_discriminator(sub, f"{path}/{idx}")


def _do_merge(target: Any, patch: Any) -> Any:
    if not isinstance(patch, dict):
        return copy.deepcopy(patch)
    out: dict[str, Any] = copy.deepcopy(target) if isinstance(target, dict) else {}
    for key, value in patch.items():
        if value is None:
            out.pop(key, None)
        elif isinstance(value, dict):
            out[key] = _do_merge(out.get(key), value)
        else:
            out[key] = copy.deepcopy(value)
    return out
