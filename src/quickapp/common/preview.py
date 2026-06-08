"""Preview module decorator for conditional DI module wiring."""

_PREVIEW_MODULE_ATTR = "_is_preview_module"


def preview_module[T](cls: T) -> T:
    """Mark a DI module as preview — filtered out when preview features are disabled."""
    setattr(cls, _PREVIEW_MODULE_ATTR, True)
    return cls


def is_preview_module(module) -> bool:
    """Check whether a module instance belongs to a preview-decorated class."""
    return getattr(type(module), _PREVIEW_MODULE_ATTR, False)
