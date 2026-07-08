import logging
from collections.abc import Callable

from aidial_sdk.chat_completion.request import Message, Role

from quickapp.common.base_stage_wrapper import BaseStageWrapper
from quickapp.common.tool_call_result import tool_call_result_from_tool_message

logger = logging.getLogger(__name__)


def _stage_hook_from_tool_message(wrapper: BaseStageWrapper, msg: Message) -> Callable[[], None]:
    def _hook() -> None:
        wrapper.add_result(tool_call_result_from_tool_message(msg))

    return _hook


class DeferredStageCloseRegistry:
    """Defers stage wrapper exit until orchestrator finishes the tool-execution phase (parallel tools)."""

    def __init__(self) -> None:
        self._pending: dict[int, tuple[BaseStageWrapper, list[Callable[[], None]]]] = {}
        self._deferred_ui_by_tool_call_id: dict[
            str, tuple[BaseStageWrapper, Callable[[], None]]
        ] = {}

    def register_stage_ui_before_close(
        self,
        stage_wrapper: BaseStageWrapper,
        fn: Callable[[], None],
        *,
        tool_call_id: str | None = None,
    ) -> None:
        """Queue UI updates (e.g. add_result) to run in flush() immediately before wrapper.__exit__."""
        if tool_call_id is not None:
            self._deferred_ui_by_tool_call_id[tool_call_id] = (stage_wrapper, fn)
            return
        wid = id(stage_wrapper)
        existing = self._pending.get(wid)
        if existing is None:
            self._pending[wid] = (stage_wrapper, [fn])
        else:
            existing[1].append(fn)

    def defer_close(self, stage_wrapper: BaseStageWrapper) -> None:
        self._pending.setdefault(id(stage_wrapper), (stage_wrapper, []))

    def sync_deferred_stage_ui_with_tool_messages(self, messages: list[Message]) -> None:
        """Replace keyed deferred hooks so flush applies add_result matching current TOOL rows.

        Call after chat-completion recovery (or any rewrite of TOOL message bodies) so stage UI
        stays aligned with conversation state for any tool that registered with ``tool_call_id``.
        """
        tool_msg_by_id: dict[str, Message] = {
            m.tool_call_id: m
            for m in messages
            if m.role == Role.TOOL and m.tool_call_id is not None
        }
        for tcid, (wrapper, _old_fn) in list(self._deferred_ui_by_tool_call_id.items()):
            tool_msg = tool_msg_by_id.get(tcid)
            if tool_msg is None:
                continue
            self._deferred_ui_by_tool_call_id[tcid] = (
                wrapper,
                _stage_hook_from_tool_message(wrapper, tool_msg),
            )

    def flush(self, *, failed: bool = False) -> None:
        """Run pending UI hooks and close every deferred stage wrapper.

        On the error path (``failed=True``) wrappers are closed with failure exc-info so
        their stages render as ``FAILED``; DIAL Chat otherwise shows a stage that was
        opened but never closed as a perpetual spinner. The success path is unchanged.
        """
        exit_args: tuple[type[BaseException] | None, BaseException | None, None] = (
            (RuntimeError, RuntimeError("Request failed before the stage completed."), None)
            if failed
            else (None, None, None)
        )

        keyed_by_wrapper_id: dict[int, list[tuple[str, Callable[[], None]]]] = {}
        for tcid, (wrapper, fn) in self._deferred_ui_by_tool_call_id.items():
            keyed_by_wrapper_id.setdefault(id(wrapper), []).append((tcid, fn))

        for wid, (wrapper, hooks) in self._pending.items():
            for tcid, fn in keyed_by_wrapper_id.get(wid, []):
                try:
                    fn()
                except Exception:
                    logger.exception(
                        "Failed while applying deferred stage UI before close (tool_call_id=%s)",
                        tcid,
                    )
            for fn in hooks:
                try:
                    fn()
                except Exception:
                    logger.exception("Failed while applying deferred stage UI before close")
            try:
                wrapper.__exit__(*exit_args)
            except Exception:
                logger.exception("Failed while closing deferred stage wrapper")
        self._pending.clear()
        self._deferred_ui_by_tool_call_id.clear()


class ImmediateStageCloseRegistry:
    """Closes wrapped stages immediately on defer (used when orchestrator wiring is absent)."""

    def __init__(self) -> None:
        self._hooks_by_id: dict[int, list[Callable[[], None]]] = {}

    def register_stage_ui_before_close(
        self,
        stage_wrapper: BaseStageWrapper,
        fn: Callable[[], None],
        *,
        tool_call_id: str | None = None,
    ) -> None:
        wid = id(stage_wrapper)
        self._hooks_by_id.setdefault(wid, []).append(fn)

    def defer_close(self, stage_wrapper: BaseStageWrapper) -> None:
        wid = id(stage_wrapper)
        for fn in self._hooks_by_id.pop(wid, []):
            try:
                fn()
            except Exception:
                logger.exception("Failed while applying deferred stage UI before close")
        try:
            stage_wrapper.__exit__(None, None, None)
        except Exception:
            logger.exception("Failed while closing deferred stage wrapper")

    def flush(self, *, failed: bool = False) -> None:
        # No-op: this registry closes stages eagerly in defer_close, so there is nothing
        # to flush. The `failed` flag exists only for signature parity with the deferred
        # registry (the two are used interchangeably via a union type).
        pass
