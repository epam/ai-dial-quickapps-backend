from unittest.mock import MagicMock

import pytest
from aidial_sdk.chat_completion import Attachment, Message, Role
from aidial_sdk.chat_completion.request import FunctionCall, ToolCall

from quickapp.common.project_context import ProjectContext
from quickapp.common.tool_names import INTERNAL_ATTACHMENTS_GET_CONTENT_TOOL_NAME
from quickapp.core.agent import OrchestratorCapabilities
from quickapp.orchestrator_attachment_strategies.lazy_on_demand._attachment_acceptance import (
    _AttachmentAcceptance,
)
from quickapp.orchestrator_attachment_strategies.lazy_on_demand._get_content_keep_policy import (
    _GetContentKeepPolicy,
)

_PROJECT = ProjectContext(url="projects/b/P")


def _policy(project: ProjectContext | None) -> _GetContentKeepPolicy:
    caps = OrchestratorCapabilities(
        deployment=MagicMock(id="orch", input_attachment_types=["application/pdf"]),
    )
    return _GetContentKeepPolicy(attachment_acceptance=_AttachmentAcceptance(caps), project=project)


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
    ("project", "url", "kept"),
    [
        (None, "files/b/a.pdf", True),
        (_PROJECT, "files/b/a.pdf", True),
        (_PROJECT, "projects/b/P/files/context/a.pdf", True),
        (_PROJECT, "/projects/b/P/files/context/a.pdf", True),
        (_PROJECT, "projects/b/Other/files/context/a.pdf", False),
        (None, "projects/b/P/files/context/a.pdf", False),
    ],
)
def test_keeps_storage_paths_of_the_current_project(
    project: ProjectContext | None, url: str, kept: bool
) -> None:
    policy = _policy(project)
    messages = _get_content_turn()
    policy.prepare(messages)

    attachment = Attachment(title="a.pdf", url=url, type="application/pdf")

    assert policy.should_keep(messages, 1, attachment) is kept
