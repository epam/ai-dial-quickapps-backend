import logging
from collections.abc import Callable

from aidial_sdk.chat_completion.request import Message, Role

from quickapp.common.base_stage_wrapper import BaseStageWrapper
from quickapp.common.get_content_recovery_payload import (
    get_content_recovery_json_string,
    get_content_recovery_tool_call_result,
)
from quickapp.common.tool_message_utils import tool_function_name_for_tool_message
from quickapp.common.tool_names import INTERNAL_ATTACHMENTS_GET_CONTENT_TOOL_NAME

logger = logging.getLogger(__name__)


def _recovery_hook_for_wrapper(wrapper: BaseStageWrapper) -> Callable[[], None]:
    def _hook() -> None:
        wrapper.add_result(get_content_recovery_tool_call_result())

    return _hook


class DeferredStageCloseRegistry:
    """Defers stage wrapper exit until orchestrator finishes the tool-execution phase (parallel tools)."""

    def __init__(self) -> None:
        self._pending: list[tuple[BaseStageWrapper, list[Callable[[], None]]]] = []
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
        for w, hooks in self._pending:
            if w is stage_wrapper:
                hooks.append(fn)
                return
        self._pending.append((stage_wrapper, [fn]))

    def defer_close(self, stage_wrapper: BaseStageWrapper) -> None:
        for w, _hooks in self._pending:
            if w is stage_wrapper:
                return
        self._pending.append((stage_wrapper, []))

    def sync_deferred_stage_with_recovered_get_content_messages(
        self, messages: list[Message]
    ) -> None:
        """Align keyed deferred UI with recovered get_content TOOL rows (error JSON)."""
        recovery_json = get_content_recovery_json_string()
        for i, msg in enumerate(messages):
            if msg.role != Role.TOOL:
                continue
            if (
                tool_function_name_for_tool_message(messages, i)
                != INTERNAL_ATTACHMENTS_GET_CONTENT_TOOL_NAME
            ):
                continue
            if msg.content != recovery_json:
                continue
            tcid = msg.tool_call_id
            if not tcid:
                continue
            stored = self._deferred_ui_by_tool_call_id.get(tcid)
            if stored is None:
                continue
            wrapper, _old_fn = stored
            self._deferred_ui_by_tool_call_id[tcid] = (
                wrapper,
                _recovery_hook_for_wrapper(wrapper),
            )

    def flush(self) -> None:
        for wrapper, hooks in self._pending:
            for tcid, (w, fn) in list(self._deferred_ui_by_tool_call_id.items()):
                if w is wrapper:
                    try:
                        fn()
                    except Exception:
                        logger.exception(
                            "Failed while applying deferred stage UI before close "
                            "(tool_call_id=%s)",
                            tcid,
                        )
            for fn in hooks:
                try:
                    fn()
                except Exception:
                    logger.exception("Failed while applying deferred stage UI before close")
            try:
                wrapper.__exit__(None, None, None)
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
        del tool_call_id
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

    def flush(self) -> None:
        pass
