from enum import StrEnum


class InjectionFrequency(StrEnum):
    ALWAYS = "always"  # always inject a new pair immediately before the last USER
    APPEND_IF_CHANGED = "append_if_changed"  # inject before last USER on first call; replace in place if unchanged; inject before last USER if content changed
