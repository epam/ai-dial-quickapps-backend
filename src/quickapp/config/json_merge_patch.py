import copy
from typing import Any

_DISCRIMINATOR_KEY = "type"


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
        elif isinstance(value, list):
            out[key] = copy.deepcopy(value)
        else:
            out[key] = value
    return out
