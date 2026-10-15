from collections.abc import Collection


def validate_listed_in_allowed_tools(
    field_name: str, allowed_tools: list[str] | None, names: Collection[str] | None
) -> None:
    """Reject per-tool ``field_name`` entries that ``allowed_tools`` would drop before routing."""
    if not names or not allowed_tools:
        return
    missing = [name for name in names if name not in allowed_tools]
    if missing:
        raise ValueError(f"{field_name} entries not present in allowed_tools: {', '.join(missing)}")
