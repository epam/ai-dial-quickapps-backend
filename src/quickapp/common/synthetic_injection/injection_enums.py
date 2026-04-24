from enum import StrEnum


class InjectionPosition(StrEnum):
    AFTER_FIRST_USER = "after_first_user"  # insert after the first USER message
    BEFORE_LAST_USER = "before_last_user"  # insert before the last USER message
    END = "end"  # append after all messages


class InjectionFrequency(StrEnum):
    ONCE = "once"  # inject once; skip if already present in history
    ALWAYS = "always"  # always append; accumulates across turns
    REFRESH = "refresh"  # remove existing pair if present, then inject fresh one
