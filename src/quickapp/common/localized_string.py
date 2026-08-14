LocalizedString = str | dict[str, str]


def resolve_localized(
    value: LocalizedString,
    locale: str | None = None,
    *,
    default_locale: str = "en",
) -> str:
    """Resolve a LocalizedString to a plain string.

    When locale is given, tries an exact match, then the bare language prefix
    (e.g. "en-US" -> "en"). Falls back to default_locale, then to any entry.
    When locale is None (used for stable identifiers), only the default_locale
    and any-entry fallbacks apply.
    """
    if isinstance(value, str):
        return value
    if locale:
        if locale in value:
            return value[locale]
        lang = locale.split("-")[0].split("_")[0]
        if lang in value:
            return value[lang]
    if default_locale in value:
        return value[default_locale]
    return next(iter(value.values()), "")
