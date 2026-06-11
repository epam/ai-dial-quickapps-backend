from enum import StrEnum


class InjectionFrequency(StrEnum):
    ALWAYS = "always"  # always append a new pair; accumulates across turns
    APPEND_IF_CHANGED = "append_if_changed"  # append new pair only if content changed since last injection for same tool+args
