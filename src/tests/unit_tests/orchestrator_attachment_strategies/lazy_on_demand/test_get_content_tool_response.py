from quickapp.common.file_reference_pattern import to_file_url_reference
from quickapp.orchestrator_attachment_strategies.lazy_on_demand._get_content_tool_response import (
    GET_CONTENT_RESPONSE_STATE_KEY,
    HISTORY_ATTACHMENT_REMOVED_STATUS_MESSAGE,
    GetContentToolResponse,
)


class TestGetContentToolResponse:
    def test_success_response_uses_file_url_reference(self):
        payload = GetContentToolResponse.success(
            display_url="files/bucket/a.pdf",
            title="a.pdf",
            mime_type="application/pdf",
        )
        assert payload.status == "Success"
        assert payload.attachment_url == to_file_url_reference("files/bucket/a.pdf")
        assert payload.status_message is None
        assert payload.to_state_entry() == {
            "status": "Success",
            "attachment_url": "file:url::files/bucket/a.pdf",
            "title": "a.pdf",
            "type": "application/pdf",
        }

    def test_success_response_for_history_adds_status_message(self):
        payload = GetContentToolResponse.for_history(
            display_url="files/bucket/a.pdf",
            title="a.pdf",
            mime_type="application/pdf",
        )
        assert payload.status_message == HISTORY_ATTACHMENT_REMOVED_STATUS_MESSAGE
        assert "when you need the content" in payload.status_message
        assert "Do not ask the user to re-upload" in payload.status_message

    def test_fail_response(self):
        payload = GetContentToolResponse.fail(message="nope", accepted_types=["application/pdf"])
        assert payload.to_state_entry() == {
            "status": "Fail",
            "status_message": "nope",
            "accepted_types": ["application/pdf"],
        }

    def test_tool_parts(self):
        response = GetContentToolResponse.success(
            display_url="files/bucket/a.pdf",
            title="a.pdf",
            mime_type="application/pdf",
        )
        content, state = response.tool_parts()
        assert 'Loaded file "a.pdf"' in content
        assert to_file_url_reference("files/bucket/a.pdf") in content
        assert GET_CONTENT_RESPONSE_STATE_KEY in state
        assert GetContentToolResponse.from_state(state) == response

    def test_content_summary_for_fail_includes_accepted_types(self):
        response = GetContentToolResponse.fail(message="nope", accepted_types=["application/pdf"])
        summary = response.content_summary()
        assert "Failed to load attachment: nope." in summary
        assert "Accepted MIME types: application/pdf." in summary

    def test_from_state_returns_none_for_missing_key(self):
        assert GetContentToolResponse.from_state({}) is None
        assert GetContentToolResponse.from_state({"other": 1}) is None
