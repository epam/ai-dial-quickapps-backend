from pathlib import PurePosixPath
from typing import Any, ClassVar

from aidial_client._exception import DialException, EtagMismatchError
from injector import AssistedBuilder, inject

from quickapp.common import StagedBaseTool, ToolCallResult
from quickapp.common.abstract.base_tool_argument_transformer import ToolArgumentTransformer
from quickapp.common.base_stage_wrapper import BaseStageWrapper
from quickapp.common.chat_completion_stream.argument_stream_presentation import ArgumentStreamMode
from quickapp.common.exceptions import InvalidToolCallParameterException
from quickapp.common.perf_timer.perf_timer import PerformanceTimer
from quickapp.config.application import StageDisplayLevel
from quickapp.config.tools.internal import InternalTool
from quickapp.dial_core_services.dial_file_service import DialFileService
from quickapp.shared.external_fetch.external_url_fetcher import (
    ExternalFetchDisabledError,
    ExternalFetchError,
    FetchedBytes,
)
from quickapp.shared.external_fetch.web_content_fetcher import (
    WebContentFetcher,
    WebContentFetchError,
)
from quickapp.shared.home_path.home_path_resolver import HomePathResolver
from quickapp.web_tooling._truncation import (
    TRUNCATION_NOTICE_TEMPLATE,
    compose_truncated_content,
    separator_byte_length,
)
from quickapp.web_tooling._web_fetch_stage_wrapper import _WebFetchStageWrapper
from quickapp.web_tooling._web_fetch_tool_error_exception import WebFetchToolErrorException

# Preview of a textual save, short enough to stay below the offload threshold.
_PREVIEW_CHARS = 1000

# Bound on collision-avoidance retries when the target filename already exists.
_MAX_UNIQUE_ATTEMPTS = 100


@inject
class _WebFetchTool(StagedBaseTool):
    """``internal_web_fetch`` — fetch an external URL, then read it or save it.

    ``save_path`` omitted: the body must decode as UTF-8 text and is returned
    inline (truncated to its head with a leading notice once it reaches
    ``max_inline_size``); a binary body is rejected. ``save_path`` given: the
    fetched bytes are persisted under the agent home and the saved path (+ a
    short preview for text) is returned, without surfacing the file to the user
    choice (``result.attachments`` stays empty).
    """

    argument_stream_mode: ClassVar[ArgumentStreamMode | None] = (
        _WebFetchStageWrapper.argument_stream_mode
    )

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

        fetched = await self.__fetch(url)

        if save_path is None:
            result = self.__load_into_context(url, fetched)
        else:
            result = await self.__save_to_workspace(save_path, fetched)

        if stage_wrapper:
            stage_wrapper.add_result(result)
        return result

    async def __fetch(self, url: str) -> FetchedBytes:
        try:
            return await self.__web_content_fetcher.fetch_external(url)
        except WebContentFetchError as e:
            # Wrong kind of URL (DIAL path / unsupported scheme): a parameter the
            # model should correct and retry.
            raise InvalidToolCallParameterException("url", str(e)) from e
        except (ExternalFetchError, ExternalFetchDisabledError) as e:
            # The URL is valid; the fetch itself failed (egress policy, size,
            # timeout, ...). A tool error, not a bad parameter.
            raise WebFetchToolErrorException(self._resolve_tool_name(), str(e)) from e

    def __load_into_context(self, url: str, fetched: FetchedBytes) -> ToolCallResult:
        text = _try_decode_utf8(fetched.data)
        if text is None:
            raise WebFetchToolErrorException(
                self._resolve_tool_name(),
                f"URL {url} returned non-text content (content-type: "
                f"{fetched.content_type or 'unknown'}); it cannot be loaded into context. "
                "Re-call with a save_path to persist it to the workspace, then use your "
                "available tools on it.",
            )

        content_type = fetched.content_type or "text/plain"
        # Keep unbounded content out of the LLM context: at or above the cap the
        # head is returned with a leading truncation notice, never an error.
        if len(fetched.data) >= self.__max_inline_size:
            text = self.__truncate_with_notice(fetched.data, content_type)
        return ToolCallResult(content=text, content_type=content_type)

    def __truncate_with_notice(self, data: bytes, content_type: str) -> str:
        # Notice first so it stays visible; reserve its byte length (+ separator
        # + 1) from the head budget so notice + head stays strictly below the cap
        # and never reaches the offload trigger (cap == threshold by default).
        notice = TRUNCATION_NOTICE_TEMPLATE.format(total=len(data), content_type=content_type)
        reserved = len(notice.encode("utf-8")) + separator_byte_length() + 1
        budget = max(self.__max_inline_size - reserved, 0)
        # "ignore" drops only a UTF-8 sequence split by the byte cut.
        head = data[:budget].decode("utf-8", errors="ignore")
        return compose_truncated_content(notice, head)

    async def __save_to_workspace(self, save_path: str, fetched: FetchedBytes) -> ToolCallResult:
        # A ``files/``-prefixed path would be returned verbatim by
        # ``resolve_appdata_url``, escaping the agent home. Require a home-relative one.
        if save_path.startswith("files/"):
            raise InvalidToolCallParameterException(
                "save_path",
                "save_path must be a workspace-relative path under the agent home "
                "(e.g. 'data.py' or 'docs/readme.md'), not an absolute 'files/...' URL.",
            )

        content_type = fetched.content_type or "application/octet-stream"
        display_path = await self.__write_unique(save_path, fetched.data, content_type)

        content = f"Saved {display_path} ({content_type}, {len(fetched.data)} bytes)."
        preview = _try_decode_utf8(fetched.data)
        if preview is not None:
            content = f"{content}\n\nPreview:\n{preview[:_PREVIEW_CHARS]}"

        return ToolCallResult(content=content, content_type="text/plain")

    async def __write_unique(self, save_path: str, data: bytes, content_type: str) -> str:
        """Write ``data`` at ``save_path`` under the agent home, uniquifying on collision.

        Uses ``overwrite=False`` so an existing file is never clobbered: on an
        ``If-None-Match`` failure the name is uniquified (``name-1.ext``, …) and
        retried. Returns the workspace-relative display path actually written.
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


def _try_decode_utf8(data: bytes) -> str | None:
    """Return ``data`` decoded as UTF-8, or ``None`` if it is not valid UTF-8."""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _with_suffix(path: str, n: int) -> str:
    """Insert ``-n`` before the extension: ``data.py`` -> ``data-1.py``."""
    pure = PurePosixPath(path)
    suffix = "".join(pure.suffixes)
    stem = path[: -len(suffix)] if suffix else path
    return f"{stem}-{n}{suffix}"
