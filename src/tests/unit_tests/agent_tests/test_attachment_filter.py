from unittest.mock import MagicMock

from aidial_sdk.chat_completion import Attachment, CustomContent, Message, Role
from aidial_sdk.chat_completion.request import FunctionCall, ToolCall

from quickapp.agent._attachment_filter import _AttachmentFilter
from quickapp.agent.orchestrator_capabilities import OrchestratorCapabilities
from quickapp.attachment_processing._legacy_user_image_keep_policy import _LegacyUserImageKeepPolicy
from quickapp.common.tool_names import INTERNAL_ATTACHMENTS_GET_CONTENT_TOOL_NAME
from quickapp.config.application import ApplicationConfig
from quickapp.config.context import FileContextConfig
from quickapp.orchestrator_attachment_strategies.lazy_on_demand._get_content_keep_policy import (
    _GetContentKeepPolicy,
)
from tests.unit_tests.attachment_processing_tests._folder_context_helpers import (
    empty_expanded_context_file_urls,
)


def _make_filter(
    contexts: list | None = None, input_attachment_types: list[str] | None = None
) -> _AttachmentFilter:
    app = MagicMock(spec=ApplicationConfig)
    app.contexts = contexts if contexts is not None else []
    patterns = ["image/*"] if input_attachment_types is None else input_attachment_types
    caps = OrchestratorCapabilities(
        deployment=MagicMock(id="orch", input_attachment_types=patterns)
    )
    keep_policy = _GetContentKeepPolicy(
        app_config=app,
        orchestrator_capabilities=caps,
        expanded_file_urls=empty_expanded_context_file_urls(),
    )
    return _AttachmentFilter(tool_attachment_keep_policies=[keep_policy])


def _msg(
    role: Role, content: str | None = "", attachments: list[Attachment] | None = None
) -> Message:
    msg = Message(role=role, content=content)
    if attachments:
        msg.custom_content = CustomContent(attachments=attachments)
    return msg


def _user_msg(content: str = "", attachments: list[Attachment] | None = None) -> Message:
    return _msg(Role.USER, content, attachments)


def _attachment(
    title: str,
    url: str,
    mime_type: str,
    reference_url: str | None = None,
) -> Attachment:
    return Attachment(
        title=title,
        url=url,
        type=mime_type,
        reference_url=reference_url,
    )


class Test_AttachmentFilter:
    def test_image_attachments_kept_inline(self):
        transformer = _make_filter()
        msg = _user_msg(
            "look at this",
            [_attachment("photo.png", "/files/photo.png", "image/png")],
        )
        result = transformer.transform([msg])
        assert len(result[0].custom_content.attachments) == 0

    def test_non_image_attachments_removed(self):
        transformer = _make_filter()
        msg = _user_msg(
            "check this",
            [_attachment("doc.pdf", "/files/doc.pdf", "application/pdf")],
        )
        result = transformer.transform([msg])
        assert len(result[0].custom_content.attachments) == 0

    def test_xml_metadata_injected_for_attachments(self):
        transformer = _make_filter()
        msg = _user_msg(
            "original content",
            [
                _attachment("doc.pdf", "/files/doc.pdf", "application/pdf"),
                _attachment("photo.png", "/files/photo.png", "image/png"),
            ],
        )
        result = transformer.transform([msg])
        content = str(result[0].content)
        assert "<attachments>" in content
        assert "<title>doc.pdf</title>" in content
        assert "<type>application/pdf</type>" in content
        assert "<title>photo.png</title>" in content
        assert "<type>image/png</type>" in content

        # USER attachments are removed from custom_content, XML metadata remains.
        assert len(result[0].custom_content.attachments) == 0

    def test_mixed_attachments_only_images_kept(self):
        transformer = _make_filter()
        msg = _user_msg(
            "",
            [
                _attachment("doc.pdf", "/files/doc.pdf", "application/pdf"),
                _attachment("photo.png", "/files/photo.png", "image/png"),
                _attachment("data.csv", "/files/data.csv", "text/csv"),
                _attachment("chart.jpg", "/files/chart.jpg", "image/jpeg"),
            ],
        )
        result = transformer.transform([msg])
        attachments = result[0].custom_content.attachments
        assert len(attachments) == 0

    def test_filter_does_not_mutate_original_messages(self):
        transformer = _make_filter()
        msg = _user_msg(
            "hello",
            [_attachment("doc.pdf", "/files/doc.pdf", "application/pdf")],
        )
        original_content = str(msg.content)
        original_attachment_count = len(msg.custom_content.attachments)

        transformer.transform([msg])

        assert str(msg.content) == original_content
        assert len(msg.custom_content.attachments) == original_attachment_count

    def test_filter_idempotent_on_repeated_calls(self):
        """Calling transform twice on the same list produces identical output."""
        transformer = _make_filter()
        msg = _user_msg(
            "hello",
            [_attachment("doc.pdf", "/files/doc.pdf", "application/pdf")],
        )
        messages = [msg]

        first_pass = transformer.transform(messages)
        first_content = str(first_pass[0].content)

        second_pass = transformer.transform(messages)
        second_content = str(second_pass[0].content)

        assert first_content == second_content
        assert first_content.count("<title>doc.pdf</title>") == 1

    # --- Multi-message tests ---

    def test_multi_message_each_filtered_independently(self):
        transformer = _make_filter()
        msg1 = _user_msg(
            "first",
            [
                _attachment("doc.pdf", "/files/doc.pdf", "application/pdf"),
                _attachment("photo.png", "/files/photo.png", "image/png"),
            ],
        )
        msg2 = _user_msg(
            "second",
            [_attachment("data.csv", "/files/data.csv", "text/csv")],
        )
        result = transformer.transform([msg1, msg2])

        # First message: all attachments removed
        assert len(result[0].custom_content.attachments) == 0
        content0 = str(result[0].content)
        assert "<title>doc.pdf</title>" in content0
        assert "<title>photo.png</title>" in content0

        # Second message: csv removed
        assert len(result[1].custom_content.attachments) == 0
        content1 = str(result[1].content)
        assert "<title>data.csv</title>" in content1

    def test_multi_message_non_attachment_messages_unchanged(self):
        transformer = _make_filter()
        plain_msg = _user_msg("just text")
        attach_msg = _user_msg(
            "with file",
            [_attachment("doc.pdf", "/files/doc.pdf", "application/pdf")],
        )
        result = transformer.transform([plain_msg, attach_msg])

        # Plain message is passed through as-is (same object, no deepcopy)
        assert result[0] is plain_msg
        assert result[0].content == "just text"

        # Attachment message is filtered
        assert "<title>doc.pdf</title>" in str(result[1].content)

    # --- Role-based tests ---

    def test_assistant_message_attachments_stripped_without_xml(self):
        transformer = _make_filter()
        msg = _msg(
            Role.ASSISTANT,
            "response",
            [_attachment("photo.png", "/files/photo.png", "image/png")],
        )
        result = transformer.transform([msg])
        # Non-USER roles: images are NOT kept inline
        assert len(result[0].custom_content.attachments) == 0
        # ASSISTANT messages do not get XML metadata injected — those attachments
        # came from the model's own prior output and would create few-shot bias.
        content = str(result[0].content)
        assert "<attachments>" not in content
        assert content == "response"

    def test_tool_message_attachments_stripped(self):
        transformer = _make_filter()
        msg = _msg(
            Role.TOOL,
            "tool output",
            [_attachment("result.png", "/files/result.png", "image/png")],
        )
        result = transformer.transform([msg])
        assert len(result[0].custom_content.attachments) == 0
        content = str(result[0].content)
        assert "<title>result.png</title>" in content

    # --- Edge case tests ---

    def test_empty_message_list(self):
        transformer = _make_filter()
        result = transformer.transform([])
        assert result == []

    def test_content_none_with_attachments(self):
        transformer = _make_filter()
        msg = _msg(
            Role.USER,
            None,
            [_attachment("doc.pdf", "/files/doc.pdf", "application/pdf")],
        )
        result = transformer.transform([msg])
        content = str(result[0].content)
        assert "<attachments>" in content
        assert "<title>doc.pdf</title>" in content

    def test_reference_url_conditional_absent(self):
        transformer = _make_filter()
        msg = _user_msg(
            "test",
            [_attachment("doc.pdf", "/files/doc.pdf", "application/pdf")],
        )
        result = transformer.transform([msg])
        content = str(result[0].content)
        # reference_url is None by default → no element
        assert "<reference_url>" not in content

    def test_reference_url_conditional_present(self):
        transformer = _make_filter()
        msg = _user_msg(
            "test",
            [
                _attachment(
                    "doc.pdf",
                    "/files/doc.pdf",
                    "application/pdf",
                    reference_url="/refs/doc.pdf",
                )
            ],
        )
        result = transformer.transform([msg])
        content = str(result[0].content)
        assert "<reference_url>/refs/doc.pdf</reference_url>" in content

    def test_fetch_tool_pdf_retained_when_whitelisted(self):
        url = "files/bucket/report.pdf"
        contexts = [FileContextConfig(url=url)]
        transformer = _make_filter(contexts=contexts, input_attachment_types=["application/pdf"])
        assistant = Message(
            role=Role.ASSISTANT,
            content="",
            tool_calls=[
                ToolCall(
                    id="call_fetch_1",
                    type="function",
                    function=FunctionCall(
                        name=INTERNAL_ATTACHMENTS_GET_CONTENT_TOOL_NAME,
                        arguments='{"attachment_url": "files/bucket/report.pdf"}',
                    ),
                )
            ],
        )
        tool_msg = Message(
            role=Role.TOOL,
            content='{"ok": true}',
            tool_call_id="call_fetch_1",
            custom_content=CustomContent(
                attachments=[_attachment("report.pdf", url, "application/pdf")]
            ),
        )
        result = transformer.transform([assistant, tool_msg])
        assert len(result[1].custom_content.attachments) == 1
        assert result[1].custom_content.attachments[0].type == "application/pdf"

    def test_fetch_tool_attachment_with_empty_type_kept_via_url_fallback(self):
        """The keep policy must use the same MIME inference (URL-filename
        fallback) the synthetic injector uses — otherwise an attachment whose
        ``type`` is empty but whose URL implies an accepted MIME would be
        injected upstream and then silently stripped here."""
        url = "files/bucket/report.pdf"
        contexts = [FileContextConfig(url=url)]
        transformer = _make_filter(contexts=contexts, input_attachment_types=["application/pdf"])
        assistant = Message(
            role=Role.ASSISTANT,
            content="",
            tool_calls=[
                ToolCall(
                    id="call_fetch_empty_type",
                    type="function",
                    function=FunctionCall(
                        name=INTERNAL_ATTACHMENTS_GET_CONTENT_TOOL_NAME,
                        arguments='{"attachment_url": "files/bucket/report.pdf"}',
                    ),
                )
            ],
        )
        tool_msg = Message(
            role=Role.TOOL,
            content='{"ok": true}',
            tool_call_id="call_fetch_empty_type",
            custom_content=CustomContent(attachments=[_attachment("report.pdf", url, "")]),
        )
        result = transformer.transform([assistant, tool_msg])
        assert len(result[1].custom_content.attachments) == 1
        assert result[1].custom_content.attachments[0].url == url

    def test_fetch_tool_pdf_stripped_for_non_fetch_tool_name(self):
        url = "files/bucket/report.pdf"
        contexts = [FileContextConfig(url=url)]
        transformer = _make_filter(contexts=contexts, input_attachment_types=["application/pdf"])
        assistant = Message(
            role=Role.ASSISTANT,
            content="",
            tool_calls=[
                ToolCall(
                    id="call_other",
                    type="function",
                    function=FunctionCall(name="some_other_tool", arguments="{}"),
                )
            ],
        )
        tool_msg = Message(
            role=Role.TOOL,
            content="out",
            tool_call_id="call_other",
            custom_content=CustomContent(
                attachments=[_attachment("report.pdf", url, "application/pdf")]
            ),
        )
        result = transformer.transform([assistant, tool_msg])
        assert len(result[1].custom_content.attachments) == 0

    def test_fetch_tool_pdf_stripped_when_url_not_in_config(self):
        url = "files/bucket/report.pdf"
        transformer = _make_filter(contexts=[], input_attachment_types=["application/pdf"])
        assistant = Message(
            role=Role.ASSISTANT,
            content="",
            tool_calls=[
                ToolCall(
                    id="call_fetch_2",
                    type="function",
                    function=FunctionCall(
                        name=INTERNAL_ATTACHMENTS_GET_CONTENT_TOOL_NAME,
                        arguments="{}",
                    ),
                )
            ],
        )
        tool_msg = Message(
            role=Role.TOOL,
            content="out",
            tool_call_id="call_fetch_2",
            custom_content=CustomContent(
                attachments=[_attachment("report.pdf", url, "application/pdf")]
            ),
        )
        result = transformer.transform([assistant, tool_msg])
        assert len(result[1].custom_content.attachments) == 0

    def test_fetch_tool_pdf_kept_when_url_matches_user_attachment(self):
        url = "files/bucket/user-report.pdf"
        transformer = _make_filter(contexts=[], input_attachment_types=["application/pdf"])
        user_msg = _user_msg(
            "please use my report",
            [_attachment("user-report.pdf", url, "application/pdf")],
        )
        assistant = Message(
            role=Role.ASSISTANT,
            content="",
            tool_calls=[
                ToolCall(
                    id="call_fetch_3",
                    type="function",
                    function=FunctionCall(
                        name=INTERNAL_ATTACHMENTS_GET_CONTENT_TOOL_NAME,
                        arguments='{"attachment_url": "files/bucket/user-report.pdf"}',
                    ),
                )
            ],
        )
        tool_msg = Message(
            role=Role.TOOL,
            content='{"ok": true}',
            tool_call_id="call_fetch_3",
            custom_content=CustomContent(
                attachments=[_attachment("user-report.pdf", url, "application/pdf")]
            ),
        )
        result = transformer.transform([user_msg, assistant, tool_msg])
        assert len(result[2].custom_content.attachments) == 1
        assert result[2].custom_content.attachments[0].url == url


def _attachment_filter_with_legacy_policy() -> _AttachmentFilter:
    """Mirror production wiring when no ``attachment_strategy`` is configured:
    only the legacy USER image keep policy is registered. The get-content policy
    is added by ``LazyOnDemandStrategyModule`` and so is absent here."""
    return _AttachmentFilter(tool_attachment_keep_policies=[_LegacyUserImageKeepPolicy()])


class Test_AttachmentFilter_LegacyUserImagePassthrough:
    """Regression guard for the `development`-branch behaviour: USER `image/*`
    attachments survive `_AttachmentFilter` when the legacy keep policy is wired
    (i.e. attachment_strategy is not configured)."""

    def test_user_image_kept(self):
        transformer = _attachment_filter_with_legacy_policy()
        msg = _user_msg(
            "look at this",
            [_attachment("photo.png", "/files/photo.png", "image/png")],
        )
        result = transformer.transform([msg])
        attachments = result[0].custom_content.attachments
        assert len(attachments) == 1
        assert attachments[0].type == "image/png"

    def test_user_image_kept_alongside_xml_metadata(self):
        transformer = _attachment_filter_with_legacy_policy()
        msg = _user_msg(
            "original content",
            [_attachment("photo.png", "/files/photo.png", "image/png")],
        )
        result = transformer.transform([msg])
        attachments = result[0].custom_content.attachments
        assert len(attachments) == 1
        # XML metadata is still surfaced into content (legacy behaviour).
        content = str(result[0].content)
        assert "<title>photo.png</title>" in content
        assert "<type>image/png</type>" in content

    def test_user_non_image_dropped(self):
        transformer = _attachment_filter_with_legacy_policy()
        msg = _user_msg(
            "doc",
            [_attachment("doc.pdf", "/files/doc.pdf", "application/pdf")],
        )
        result = transformer.transform([msg])
        assert len(result[0].custom_content.attachments) == 0

    def test_assistant_image_still_stripped(self):
        transformer = _attachment_filter_with_legacy_policy()
        msg = _msg(
            Role.ASSISTANT,
            "response",
            [_attachment("photo.png", "/files/photo.png", "image/png")],
        )
        result = transformer.transform([msg])
        assert len(result[0].custom_content.attachments) == 0

    def test_tool_image_still_stripped(self):
        transformer = _attachment_filter_with_legacy_policy()
        msg = _msg(
            Role.TOOL,
            "tool output",
            [_attachment("photo.png", "/files/photo.png", "image/png")],
        )
        result = transformer.transform([msg])
        assert len(result[0].custom_content.attachments) == 0

    def test_user_mixed_only_images_kept(self):
        transformer = _attachment_filter_with_legacy_policy()
        msg = _user_msg(
            "",
            [
                _attachment("doc.pdf", "/files/doc.pdf", "application/pdf"),
                _attachment("photo.png", "/files/photo.png", "image/png"),
                _attachment("chart.jpg", "/files/chart.jpg", "image/jpeg"),
                _attachment("data.csv", "/files/data.csv", "text/csv"),
            ],
        )
        result = transformer.transform([msg])
        attachments = result[0].custom_content.attachments
        kept_types = sorted(att.type for att in attachments)
        assert kept_types == ["image/jpeg", "image/png"]
