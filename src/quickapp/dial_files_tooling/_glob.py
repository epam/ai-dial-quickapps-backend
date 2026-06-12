import glob
import re

from quickapp.common.exceptions import InvalidToolCallParameterException


def _glob_to_regex(pattern: str) -> re.Pattern[str]:
    """Translate a glob into a compiled, segment-aware regex.

    Used by both `find` (its `pattern`) and `search` (its `name_filter`) so the two
    tools accept exactly the same glob dialect. Delegates to the stdlib
    ``glob.translate`` (Python 3.13+) with:

    - ``recursive=True`` so ``**`` spans path segments (``**/x`` matches ``x``, ``a/x``,
      ``a/b/x``) while a lone ``*`` / ``?`` stays within one segment (does not cross ``/``).
    - ``include_hidden=True`` so dotfiles are matched like any other name.
    - ``seps="/"`` because DIAL paths always use ``/``.

    The result is anchored and case-sensitive (consistent with DIAL paths).
    """
    if not isinstance(pattern, str) or pattern == "":
        raise InvalidToolCallParameterException("pattern", "pattern must be a non-empty string")

    try:
        return re.compile(glob.translate(pattern, recursive=True, include_hidden=True, seps="/"))
    except (re.error, ValueError) as e:
        raise InvalidToolCallParameterException("pattern", f"invalid glob pattern: {e}") from e
