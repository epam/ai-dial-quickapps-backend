from enum import StrEnum


class InjectionPosition(StrEnum):
    AFTER_FIRST_USER = "after_first_user"  # insert after the first USER message
    BEFORE_LAST_USER = "before_last_user"  # insert before the last USER message
    END = "end"  # append after all messages


class InjectionFrequency(StrEnum):
    ALWAYS = "always"  # always append a new pair; accumulates across turns
    APPEND_IF_CHANGED = "append_if_changed"  # append new pair only if content changed since last injection for same tool+args
    REFRESH_IF_CHANGED = (
        "refresh_if_changed"  # replace last pair for same tool+args only if content changed
    )
