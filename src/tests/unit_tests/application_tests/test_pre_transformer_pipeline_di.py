"""Tests that verify the pre-transformer pipeline ordering using DI.

The pipeline runs transformers sequentially via _MessagesSetup:

    _AddSystemPromptTransformer -> _AttachmentNotificationInjector

- _AddSystemPromptTransformer ensures a system message exists at the start of the conversation.
- _AttachmentNotificationInjector handles admin-configured context files by injecting
  synthetic tool call/result messages.
"""

import json

from aidial_sdk.chat_completion import Attachment, CustomContent, Message, Role
from fastapi_injector import Injected
from injector import Binder
from starlette.testclient import TestClient

from quickapp.application._messages_setup import _MessagesSetup
from quickapp.attachment_processing._tool_configs import AVAILABLE_CONTEXT_TOOL_NAME
from quickapp.attachment_processing.attachment_processing_module import AttachmentProcessingModule
from quickapp.config.application import ApplicationConfig
from quickapp.config.context import FileContextConfig
from tests.unit_tests.common.common import create_app_configuration, create_test_app


def _user_msg(content: str = "", attachments: list[Attachment] | None = None) -> Message:
    msg = Message(role=Role.USER, content=content)
    if attachments:
        msg.custom_content = CustomContent(attachments=attachments)
    return msg


def _attachment(title: str, url: str, mime_type: str) -> Attachment:
    return Attachment(
        title=title,
        url=url,
        type=mime_type,
    )


def _make_context_app(ctx_url: str):
    ctx = FileContextConfig(url=ctx_url, description="Reference doc")

    def configure(binder: Binder):
        app_config = create_app_configuration([])
        app_config.contexts = [ctx]
        binder.bind(ApplicationConfig, to=app_config)

    return create_test_app([AttachmentProcessingModule, configure])


def test_context_file_notified_via_synthetic_tool_call():
    app = _make_context_app("files/bucket/reference.pdf")
    client = TestClient(app)

    @app.get("/test_context")
    async def get_method(messages_setup: _MessagesSetup = Injected(_MessagesSetup)):
        messages = [_user_msg("hello")]

        result = await messages_setup.setup(messages)

        # Original + synthetic assistant tool_call + tool result
        assert len(result) == 3
        assert result[1].role == Role.ASSISTANT
        assert result[1].tool_calls[0].function.name == AVAILABLE_CONTEXT_TOOL_NAME

        data = json.loads(result[2].content)
        assert len(data["entries"]) == 1
        assert data["entries"][0]["title"] == "reference.pdf"
        assert data["entries"][0]["url"] == "files/bucket/reference.pdf"
        assert data["entries"][0]["status"] == "new"

        return {"message": "success"}

    response = client.get("/test_context")

    assert response.status_code == 200
    assert response.json() == {"message": "success"}


def test_user_attachment_text_and_context_tool_call():
    app = _make_context_app("files/bucket/ref.csv")
    client = TestClient(app)

    @app.get("/test_combined")
    async def get_method(messages_setup: _MessagesSetup = Injected(_MessagesSetup)):
        messages = [
            _user_msg(
                "check",
                [_attachment("doc.pdf", "/files/doc.pdf", "application/pdf")],
            )
        ]

        result = await messages_setup.setup(messages)

        # Original message + 2 synthetic messages for context
        assert len(result) == 3

        # Context notified via synthetic tool call
        assert result[1].tool_calls[0].function.name == AVAILABLE_CONTEXT_TOOL_NAME
        data = json.loads(result[2].content)
        assert data["entries"][0]["title"] == "ref.csv"

        return {"message": "success"}

    response = client.get("/test_combined")

    assert response.status_code == 200
    assert response.json() == {"message": "success"}
