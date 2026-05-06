from unittest.mock import Mock

from aidial_sdk.chat_completion.request import FunctionCall, Message, Role, ToolCall

from quickapp.common.base_stage_wrapper import BaseStageWrapper
from quickapp.common.get_content_recovery_payload import get_content_recovery_tool_call_result
from quickapp.common.stage_close_registry import (
    DeferredStageCloseRegistry,
    ImmediateStageCloseRegistry,
)
from quickapp.common.tool_names import INTERNAL_ATTACHMENTS_GET_CONTENT_TOOL_NAME


def test_deferred_flush_runs_registered_ui_hooks_before_exit():
    registry = DeferredStageCloseRegistry()
    wrapper = Mock(spec=BaseStageWrapper)
    order: list[str] = []

    def hook() -> None:
        order.append("hook")

    wrapper.__exit__ = Mock(side_effect=lambda *a, **k: order.append("exit"))

    registry.register_stage_ui_before_close(wrapper, hook)
    registry.defer_close(wrapper)
    registry.flush()

    assert order == ["hook", "exit"]
    wrapper.__exit__.assert_called_once_with(None, None, None)


def test_deferred_defer_close_before_register_still_orders_hooks_before_exit():
    registry = DeferredStageCloseRegistry()
    wrapper = Mock(spec=BaseStageWrapper)
    order: list[str] = []

    wrapper.__exit__ = Mock(side_effect=lambda *a, **k: order.append("exit"))

    registry.defer_close(wrapper)
    registry.register_stage_ui_before_close(wrapper, lambda: order.append("hook"))
    registry.flush()

    assert order == ["hook", "exit"]


def test_immediate_defer_close_runs_registered_hooks_before_exit():
    registry = ImmediateStageCloseRegistry()
    wrapper = Mock(spec=BaseStageWrapper)
    order: list[str] = []

    wrapper.__exit__ = Mock(side_effect=lambda *a, **k: order.append("exit"))

    registry.register_stage_ui_before_close(wrapper, lambda: order.append("hook"))
    registry.defer_close(wrapper)

    assert order == ["hook", "exit"]


def test_sync_rewrites_keyed_hook_so_flush_adds_recovery_result():
    registry = DeferredStageCloseRegistry()
    wrapper = Mock(spec=BaseStageWrapper)
    wrapper.__exit__ = Mock(return_value=False)

    success_called = {"n": 0}

    def success_hook() -> None:
        success_called["n"] += 1

    registry.register_stage_ui_before_close(wrapper, success_hook, tool_call_id="tc-sync")
    registry.defer_close(wrapper)

    messages = [
        Message(role=Role.USER, content="hi"),
        Message(
            role=Role.ASSISTANT,
            content=" ",
            tool_calls=[
                ToolCall(
                    id="tc-sync",
                    type="function",
                    function=FunctionCall(
                        name=INTERNAL_ATTACHMENTS_GET_CONTENT_TOOL_NAME,
                        arguments="{}",
                    ),
                )
            ],
        ),
        Message(
            role=Role.TOOL,
            content=get_content_recovery_tool_call_result().content,
            tool_call_id="tc-sync",
        ),
    ]
    registry.sync_deferred_stage_ui_with_tool_messages(messages)
    registry.flush()

    assert success_called["n"] == 0
    wrapper.add_result.assert_called_once()
    called = wrapper.add_result.call_args[0][0]
    assert called.content == get_content_recovery_tool_call_result().content
    assert called.content_type == "application/json"
    assert called.attachments == []
