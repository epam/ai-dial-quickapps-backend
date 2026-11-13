from unittest.mock import MagicMock

import pytest
from aidial_sdk.chat_completion import Attachment, Message, Role
from aidial_sdk.chat_completion.request import FunctionCall, ToolCall

from quickapp.common.tool_names import INTERNAL_ATTACHMENTS_GET_CONTENT_TOOL_NAME
from quickapp.core.agent import OrchestratorCapabilities
from quickapp.orchestrator_attachment_strategies.lazy_on_demand._attachment_acceptance import (
    _AttachmentAcceptance,
)
from quickapp.orchestrator_attachment_strategies.lazy_on_demand._get_content_keep_policy import (
    _GetContentKeepPolicy,
)


def _policy() -> _GetContentKeepPolicy:
    caps = OrchestratorCapabilities(
        deployment=MagicMock(id="orch", input_attachment_types=["application/pdf"]),
    )
    return _GetContentKeepPolicy(attachment_acceptance=_AttachmentAcceptance(caps))


def _get_content_turn() -> list[Message]:
    assistant = Message(
        role=Role.ASSISTANT,
        content="",
        tool_calls=[
            ToolCall(
                id="call_1",
                type="function",
                function=FunctionCall(
                    name=INTERNAL_ATTACHMENTS_GET_CONTENT_TOOL_NAME, arguments="{}"
                ),
            )
        ],
    )
    return [assistant, Message(role=Role.TOOL, content="", tool_call_id="call_1")]


@pytest.mark.parametrize(
    ("url", "kept"),
    [
        ("files/b/a.pdf", True),
        ("projects/b/P/files/context/a.pdf", True),
        ("/projects/b/P/files/context/a.pdf", True),
        ("https://example.com/a.pdf", False),
        ("reports/a.pdf", False),
    ],
)
def test_keeps_dial_storage_paths(url: str, kept: bool) -> None:
    policy = _policy()
    messages = _get_content_turn()
    policy.prepare(messages)

    attachment = Attachment(title="a.pdf", url=url, type="application/pdf")

    assert policy.should_keep(messages, 1, attachment) is kept
