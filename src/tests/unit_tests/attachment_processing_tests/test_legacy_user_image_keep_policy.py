from aidial_sdk.chat_completion import Attachment, Message, Role

from quickapp.attachment_processing._legacy_user_image_keep_policy import _LegacyUserImageKeepPolicy


def _msg(role: Role) -> Message:
    return Message(role=role, content="")


def _attachment(mime_type: str | None) -> Attachment:
    return Attachment(title="x", url="/files/x", type=mime_type)


class TestLegacyUserImageKeepPolicy:
    def test_keeps_image_png_on_user_message(self):
        policy = _LegacyUserImageKeepPolicy()
        messages = [_msg(Role.USER)]
        assert policy.should_keep(messages, 0, _attachment("image/png")) is True

    def test_keeps_image_jpeg_on_user_message(self):
        policy = _LegacyUserImageKeepPolicy()
        messages = [_msg(Role.USER)]
        assert policy.should_keep(messages, 0, _attachment("image/jpeg")) is True

    def test_drops_non_image_on_user_message(self):
        policy = _LegacyUserImageKeepPolicy()
        messages = [_msg(Role.USER)]
        assert policy.should_keep(messages, 0, _attachment("application/pdf")) is False

    def test_drops_image_on_assistant_message(self):
        policy = _LegacyUserImageKeepPolicy()
        messages = [_msg(Role.ASSISTANT)]
        assert policy.should_keep(messages, 0, _attachment("image/png")) is False

    def test_drops_image_on_tool_message(self):
        policy = _LegacyUserImageKeepPolicy()
        messages = [_msg(Role.TOOL)]
        assert policy.should_keep(messages, 0, _attachment("image/png")) is False

    def test_drops_attachment_without_type(self):
        policy = _LegacyUserImageKeepPolicy()
        messages = [_msg(Role.USER)]
        assert policy.should_keep(messages, 0, _attachment(None)) is False
