from pathlib import PurePosixPath
from typing import Any

from aidial_client._exception import DialException, EtagMismatchError
from injector import AssistedBuilder, inject

from quickapp.common import StagedBaseTool, ToolCallResult
from quickapp.common.abstract.base_tool_argument_transformer import ToolArgumentTransformer
from quickapp.common.base_stage_wrapper import BaseStageWrapper
from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.common.perf_timer.perf_timer import PerformanceTimer
from quickapp.config.application import StageDisplayLevel
from quickapp.config.tools.internal import InternalTool
from quickapp.dial_core_services.dial_file_service import DialFileService
from quickapp.shared.external_fetch.web_content_fetcher import WebContentFetcher
from quickapp.shared.home_path.home_path_resolver import HomePathResolver
from quickapp.web_tooling._web_fetch_stage_wrapper import _WebFetchStageWrapper

# Preview shown for textual saves so the agent can decide whether to read the
# full file. Kept short to stay well below any offload threshold.
_PREVIEW_CHARS = 1000

# Bound on collision-avoidance retries when the target filename already exists.
_MAX_UNIQUE_ATTEMPTS = 100


@inject
class _WebFetchTool(StagedBaseTool):
    """``internal_web_fetch`` — fetch an external resource; read it or save it.

    A single optional ``save_path`` selects the behaviour:

    * **omitted** — the payload must be textual and within ``max_inline_size``;
      the decoded text is returned inline. Binary or oversized content is rejected
      with guidance to re-call with a ``save_path`` — the tool never truncates and
      never offloads. The inline cap defaults to the global offload threshold, so a
      returned result is always below the offloader's trigger
      (see docs/designs/web_fetch_tool.md, Component 4a).
    * **given** — the fetched bytes (any content type) are persisted at
      ``save_path`` under the agent home via the shared home-path resolver and a
      bytes write, and the saved workspace-relative path (+ a short preview for
      textual content) is returned so the ``internal_file_*`` tools can operate on
      it. The file is never surfaced to the user choice (``result.attachments`` is
      left empty), unlike ``_WriteFileTool``.
    """

    def __init__(
        self,
        stage_wrapper_builder: AssistedBuilder[_WebFetchStageWrapper],
        tool_config: InternalTool,
        perf_timer: PerformanceTimer,
        web_content_fetcher: WebContentFetcher,
        dial_file_service: DialFileService,
        home_resolver: HomePathResolver,
        max_inline_size: int,
        stage_display_level: StageDisplayLevel = StageDisplayLevel.INFO,
        argument_transformers: list[ToolArgumentTransformer] | None = None,
        **kwargs: Any,
    ):
        super().__init__(
            stage_wrapper_builder=stage_wrapper_builder,  # type: ignore[arg-type]
            tool_config=tool_config,
            perf_timer=perf_timer,
            stage_display_level=stage_display_level,
            argument_transformers=argument_transformers,
            **kwargs,
        )
        self.__web_content_fetcher = web_content_fetcher
        self.__dial_file_service = dial_file_service
        self.__home_resolver = home_resolver
        self.__max_inline_size = max_inline_size

    async def _run_in_stage_async(
        self,
        stage_wrapper: BaseStageWrapper | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> ToolCallResult:
        url: str = kwargs["url"]
        save_path: str | None = kwargs.get("save_path")

        fetched = await self.__web_content_fetcher.fetch_external(url, parameter_name="url")

        if save_path is None:
            result = self.__load_into_context(url, fetched)
        else:
            result = await self.__save_to_workspace(save_path, fetched)

        if stage_wrapper:
            stage_wrapper.add_result(result)
        return result

    def __load_into_context(self, url: str, fetched: Any) -> ToolCallResult:
        if not WebContentFetcher.is_textual(fetched.content_type):
            raise InvalidToolCallParameterException(
                "url",
                f"URL {url} returned non-text content "
                f"(content-type: {fetched.content_type or 'unknown'}), which cannot be "
                "loaded into context. Re-call with a save_path to persist it to the "
                "workspace instead.",
            )

        text = WebContentFetcher.decode(fetched.data, fetched.content_type)

        # Guard against dumping unbounded content into the LLM context. Reject at or
        # above the cap so the returned content stays strictly below it (and, at the
        # default where the cap equals the offload threshold, below the offloader's
        # trigger too).
        content_size = len(text.encode("utf-8"))
        if content_size >= self.__max_inline_size:
            raise InvalidToolCallParameterException(
                "url",
                f"URL {url} content is too large to load inline "
                f"({content_size} bytes >= {self.__max_inline_size} byte limit). "
                "Re-call with a save_path to persist it to the workspace, then read "
                "ranges with internal_file_read_lines / internal_file_search.",
            )

        return ToolCallResult(
            content=text,
            content_type=fetched.content_type or "text/plain",
        )

    async def __save_to_workspace(self, save_path: str, fetched: Any) -> ToolCallResult:
        # A ``files/``-prefixed path would be returned verbatim by
        # ``resolve_appdata_url`` (bypassing home-prefixing and traversal validation),
        # escaping the agent home. Require a home-relative destination.
        if save_path.startswith("files/"):
            raise InvalidToolCallParameterException(
                "save_path",
                "save_path must be a workspace-relative path under the agent home "
                "(e.g. 'data.py' or 'docs/readme.md'), not an absolute 'files/...' URL.",
            )

        content_type = fetched.content_type or "application/octet-stream"
        display_path = await self.__write_unique(save_path, fetched.data, content_type)

        size = len(fetched.data)
        content = f"Saved {display_path} ({content_type}, {size} bytes)."
        if WebContentFetcher.is_textual(fetched.content_type):
            preview = WebContentFetcher.decode(fetched.data, fetched.content_type)[:_PREVIEW_CHARS]
            content = f"{content}\n\nPreview:\n{preview}"

        return ToolCallResult(content=content, content_type="text/plain")

    async def __write_unique(self, save_path: str, data: bytes, content_type: str) -> str:
        """Write ``data`` at ``save_path`` under the agent home, uniquifying on collision.

        Uses ``overwrite=False`` so an existing file is never clobbered: on an
        ``If-None-Match`` failure the name is uniquified (``name-1.ext``,
        ``name-2.ext``, …) and retried. Returns the workspace-relative display path
        actually written.
        """
        for attempt in range(_MAX_UNIQUE_ATTEMPTS):
            candidate = save_path if attempt == 0 else _with_suffix(save_path, attempt)
            target_url = await self.__home_resolver.resolve_appdata_url(candidate)
            display_path = await self.__home_resolver.to_display_path(target_url)
            try:
                await self.__dial_file_service.write_bytes(
                    url=target_url,
                    content=data,
                    content_type=content_type,
                    overwrite=False,
                )
                return display_path
            except EtagMismatchError:
                continue
            except DialException as e:
                if e.status_code == 403:
                    raise InvalidToolCallParameterException(
                        "save_path", f"access denied: {display_path}"
                    ) from e
                raise
        raise InvalidToolCallParameterException(
            "save_path",
            f"Could not find a free filename for '{save_path}' after "
            f"{_MAX_UNIQUE_ATTEMPTS} attempts; too many saves share this name.",
        )


def _with_suffix(path: str, n: int) -> str:
    """Insert ``-n`` before the extension: ``data.py`` -> ``data-1.py``."""
    pure = PurePosixPath(path)
    suffix = "".join(pure.suffixes)
    stem = path[: -len(suffix)] if suffix else path
    return f"{stem}-{n}{suffix}"
