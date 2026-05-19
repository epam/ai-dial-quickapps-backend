from unittest.mock import Mock

import pytest
from aidial_sdk.chat_completion.request import Message, Role

from quickapp.common.chat_completion_recovery import ChatCompletionRecoveryService
from quickapp.common.messages_mixin import MessagesMixin
from quickapp.common.stage_close_registry import DeferredStageCloseRegistry


def _recovery_service(
    messages: list[Message],
    *,
    policies: list | None = None,
    deferred_registry: DeferredStageCloseRegistry | None = None,
) -> ChatCompletionRecoveryService:
    messages_mixin = Mock(spec=MessagesMixin)
    messages_mixin.messages = messages
    return ChatCompletionRecoveryService(
        messages_mixin,
        policies or [],
        deferred_registry or DeferredStageCloseRegistry(),
    )


def test_apply_recovery_syncs_stage_ui_when_policy_recovers():
    messages = [Message(role=Role.USER, content="hi")]
    error = ValueError("bad request")
    policy = Mock()
    policy.try_recover.return_value = True
    deferred_registry = Mock(spec=DeferredStageCloseRegistry)
    service = _recovery_service(messages, policies=[policy], deferred_registry=deferred_registry)

    service.apply_message_recovery(error, retry_scope="test")

    policy.try_recover.assert_called_once_with(messages, error)
    deferred_registry.sync_deferred_stage_ui_with_tool_messages.assert_called_once_with(messages)


def test_apply_recovery_raises_when_no_policy_recovers():
    messages = [Message(role=Role.USER, content="hi")]
    error = ValueError("bad request")
    policy = Mock()
    policy.try_recover.return_value = False
    deferred_registry = Mock(spec=DeferredStageCloseRegistry)
    service = _recovery_service(messages, policies=[policy], deferred_registry=deferred_registry)

    with pytest.raises(ValueError, match="bad request"):
        service.apply_message_recovery(error, retry_scope="test")

    deferred_registry.sync_deferred_stage_ui_with_tool_messages.assert_not_called()


def test_apply_recovery_raises_on_second_recoverable_failure():
    messages = [Message(role=Role.USER, content="hi")]
    error = ValueError("bad request")
    policy = Mock()
    policy.try_recover.return_value = True
    service = _recovery_service(messages, policies=[policy])

    service.apply_message_recovery(error, retry_scope="test")

    with pytest.raises(ValueError, match="bad request"):
        service.apply_message_recovery(error, retry_scope="test")

    assert policy.try_recover.call_count == 1


def test_apply_recovery_raises_on_second_scope_after_first_recovery():
    messages = [Message(role=Role.USER, content="hi")]
    error = ValueError("bad request")
    policy = Mock()
    policy.try_recover.return_value = True
    service = _recovery_service(messages, policies=[policy])

    service.apply_message_recovery(error, retry_scope="create")

    with pytest.raises(ValueError, match="bad request"):
        service.apply_message_recovery(error, retry_scope="stream")

    assert policy.try_recover.call_count == 1
