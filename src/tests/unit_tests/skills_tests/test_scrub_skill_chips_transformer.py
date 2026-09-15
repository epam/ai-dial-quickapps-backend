"""``_ScrubSkillChipsTransformer`` — the field never leaves QuickApps."""

import pytest
from aidial_sdk.chat_completion import Message, Role

from quickapp.skills._scrub_skill_chips_transformer import _ScrubSkillChipsTransformer


def _user_with_chips() -> Message:
    return Message.model_validate(
        {
            "role": "user",
            "content": "hi",
            "custom_content": {"skills": [{"url": "skills/b/a"}], "state": {"k": 1}},
        }
    )


class TestScrub:

    @pytest.mark.asyncio
    async def test_removes_the_field_and_keeps_the_rest_of_custom_content(self):
        message = _user_with_chips()

        result = await _ScrubSkillChipsTransformer().transform([message])

        assert result[0].custom_content.model_extra == {}
        assert result[0].custom_content.state == {"k": 1}
        assert result[0].content == "hi"

    @pytest.mark.asyncio
    async def test_the_request_message_is_left_untouched(self):
        message = _user_with_chips()

        await _ScrubSkillChipsTransformer().transform([message])

        assert message.custom_content.model_extra == {"skills": [{"url": "skills/b/a"}]}

    @pytest.mark.asyncio
    async def test_messages_without_the_field_are_passed_through_by_reference(self):
        messages = [
            Message(role=Role.USER, content="hi"),
            Message(role=Role.ASSISTANT, content="ok"),
        ]

        result = await _ScrubSkillChipsTransformer().transform(messages)

        assert result[0] is messages[0] and result[1] is messages[1]
