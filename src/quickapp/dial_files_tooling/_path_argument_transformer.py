import logging
from typing import Any

from injector import inject

from quickapp.common.abstract.base_tool_argument_transformer import ToolArgumentTransformer
from quickapp.dial_files_tooling._home_path_resolver import _HomePathResolver

logger = logging.getLogger(__name__)

# Path-bearing argument names across the dial-files tools. Anything else is left
# untouched (e.g. `content`, `pattern`).
_PATH_ARG_NAMES = ("path", "source", "destination")


@inject
class _AppdataHomePathTransformer(ToolArgumentTransformer):
    """Relativizes in-home absolute paths in dial-files tool arguments.

    When the model passes an absolute ``files/{bucket}/appdata/{home}/...`` URL that
    points under the agent home dir, rewrite it to the equivalent relative path. This
    keeps the agent's home prefix out of the stage title / Request panel (which echo the
    raw argument) and out of the conversation, while leaving genuinely out-of-home
    absolute URLs untouched so they still resolve (or get rejected) as before.

    Runs after the file-reference transformer so a ``file:...::`` reference already
    resolved to a ``files/...`` URL is relativized too.
    """

    def __init__(self, home_resolver: _HomePathResolver) -> None:
        self._home_resolver = home_resolver

    async def transform(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        for name in _PATH_ARG_NAMES:
            value = kwargs.get(name)
            if not isinstance(value, str) or not value.startswith("files/"):
                continue
            # to_display_path returns the URL unchanged when it is not under the agent
            # home dir, or when the appdata namespace cannot be resolved.
            relative = await self._home_resolver.to_display_path(value)
            if relative != value:
                logger.debug("Relativized argument %s: %s -> %s", name, value, relative)
                kwargs[name] = relative
        return kwargs
