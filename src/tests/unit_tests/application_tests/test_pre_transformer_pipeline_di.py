"""Tests that verify the pre-transformer pipeline ordering using DI.

The pipeline runs transformers sequentially via _MessagesSetup:

    _AddSystemPromptTransformer -> _AttachmentGetContentInjector -> _AttachmentNotificationInjector

- _AddSystemPromptTransformer ensures a system message exists at the start of the conversation.
- _AttachmentNotificationInjector handles admin-configured context files by injecting
  synthetic tool call/result messages.
"""

import json

from aidial_sdk.chat_completion import Attachment, CustomContent, Message, Role
from fastapi_injector import Injected
from injector import Binder, Module, multiprovider
from starlette.testclient import TestClient

from quickapp.application._messages_setup import _MessagesSetup
from quickapp.attachment_processing._tool_configs import AVAILABLE_CONTEXT_TOOL_NAME
from quickapp.attachment_processing.attachment_processing_module import AttachmentProcessingModule
from quickapp.common.abstract.tool_call_result_enricher import ToolCallResultEnricher
from quickapp.config.application import ApplicationConfig
from quickapp.config.context import FileContextConfig
from quickapp.config.orchestrator_attachment_strategy import LazyOnDemandAttachmentStrategy
from quickapp.orchestrator_attachment_strategies.lazy_on_demand._tool_configs import (
    GET_CONTENT_TOOL_CONFIG,
)
from quickapp.orchestrator_attachment_strategies.lazy_on_demand.lazy_on_demand_strategy_module import (
    LazyOnDemandStrategyModule,
)
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


class _EmptyEnrichersModule(Module):
    def configure(self, binder: Binder) -> None:
        pass

    @multiprovider
    def _enrichers(self) -> list[ToolCallResultEnricher]:
        return []


def _make_context_app(ctx_url: str, *, lazy_strategy: bool = False):
    ctx = FileContextConfig(url=ctx_url, description="Reference doc")

    def configure(binder: Binder):
        app_config = create_app_configuration([])
        app_config.contexts = [ctx]
        if lazy_strategy:
            app_config.orchestrator.attachment_strategy = LazyOnDemandAttachmentStrategy()
        binder.bind(ApplicationConfig, to=app_config)

    modules: list = [AttachmentProcessingModule, _EmptyEnrichersModule, configure]
    if lazy_strategy:
        modules.insert(1, LazyOnDemandStrategyModule)
    return create_test_app(modules)


def test_context_file_notified_via_synthetic_tool_call():
    app = _make_context_app("files/bucket/reference.pdf")
    client = TestClient(app)

    @app.get("/test_context")
    async def get_method(messages_setup: _MessagesSetup = Injected(_MessagesSetup)):
        messages = [_user_msg("hello")]

        result = await messages_setup.run_transformers(messages_setup.extract_tool_calls(messages))

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
    app = _make_context_app("files/bucket/ref.csv", lazy_strategy=True)
    client = TestClient(app)

    @app.get("/test_combined")
    async def get_method(messages_setup: _MessagesSetup = Injected(_MessagesSetup)):
        messages = [
            _user_msg(
                "check",
                [_attachment("doc.pdf", "/files/doc.pdf", "application/pdf")],
            )
        ]

        result = await messages_setup.run_transformers(messages_setup.extract_tool_calls(messages))

        # Original message + 2 synthetic get_content messages + 2 synthetic context messages
        assert len(result) == 5

        get_content_tool_name = GET_CONTENT_TOOL_CONFIG.open_ai_tool.function.name
        assert result[1].tool_calls[0].function.name == get_content_tool_name
        assert result[2].role == Role.TOOL
        assert result[2].custom_content is not None
        assert result[2].custom_content.attachments is not None
        assert result[2].custom_content.attachments[0].url == "/files/doc.pdf"

        # Context notified via synthetic tool call
        assert result[3].tool_calls[0].function.name == AVAILABLE_CONTEXT_TOOL_NAME
        data = json.loads(result[4].content)
        assert data["entries"][0]["title"] == "ref.csv"

        return {"message": "success"}

    response = client.get("/test_combined")

    assert response.status_code == 200
    assert response.json() == {"message": "success"}
