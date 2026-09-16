"""``_ScrubExtraFieldsTransformer`` — undeclared message fields never leave QuickApps."""

import pytest
from aidial_sdk.chat_completion import Message, Role
from aidial_sdk.utils.pydantic import model_validate_extra_fields

from quickapp.core.agent._scrub_extra_fields_transformer import (
    _extra_fields_exclude,
    _ScrubExtraFieldsTransformer,
)


def _user_with_chips() -> Message:
    return Message.model_validate(
        {
            "role": "user",
            "content": "hi",
            "custom_content": {"skills": [{"url": "skills/b/a"}], "state": {"k": 1}},
        }
    )


def _assistant_with_annotations() -> Message:
    return Message.model_validate(
        {
            "role": "assistant",
            "content": "answer [1]",
            "client_only": "x",
            "custom_content": {
                "annotations": [{"type": "url_citation", "url": "https://example.com"}],
                "attachments": [{"url": "files/b/a.txt", "title": "a.txt", "extra": 1}],
                "state": {"annotations": "kept: state is free-form"},
            },
        }
    )


class TestScrub:

    @pytest.mark.asyncio
    async def test_removes_skill_chips_and_keeps_the_rest_of_custom_content(self):
        result = await _ScrubExtraFieldsTransformer().transform([_user_with_chips()])

        assert result[0].custom_content.model_extra == {}
        assert result[0].custom_content.state == {"k": 1}
        assert result[0].content == "hi"

    @pytest.mark.asyncio
    async def test_removes_extras_at_every_level(self):
        """Chat's custom_content.annotations would otherwise be rejected by SDK-based adapters."""
        result = await _ScrubExtraFieldsTransformer().transform([_assistant_with_annotations()])

        scrubbed = result[0]
        model_validate_extra_fields(scrubbed)  # the adapters' own check
        assert scrubbed.model_extra == {}
        assert scrubbed.custom_content.model_extra == {}
        assert scrubbed.custom_content.attachments[0].model_extra == {}
        assert scrubbed.custom_content.attachments[0].url == "files/b/a.txt"
        assert scrubbed.custom_content.state == {"annotations": "kept: state is free-form"}
        assert scrubbed.content == "answer [1]"

    @pytest.mark.asyncio
    async def test_the_request_message_is_left_untouched(self):
        chips = _user_with_chips()
        annotated = _assistant_with_annotations()

        await _ScrubExtraFieldsTransformer().transform([chips, annotated])

        assert chips.custom_content.model_extra == {"skills": [{"url": "skills/b/a"}]}
        assert "annotations" in annotated.custom_content.model_extra
        assert annotated.custom_content.attachments[0].model_extra == {"extra": 1}

    @pytest.mark.asyncio
    async def test_messages_without_extras_are_passed_through_by_reference(self):
        messages = [
            Message(role=Role.USER, content="hi"),
            Message(role=Role.ASSISTANT, content="ok"),
        ]

        result = await _ScrubExtraFieldsTransformer().transform(messages)

        assert result[0] is messages[0] and result[1] is messages[1]


def test_exclude_spec_walks_lists_and_dicts_like_the_sdk():
    nested = Message.model_validate({"role": "user", "content": "x", "extra": 1})

    assert _extra_fields_exclude({"k": [nested], "plain": {"a": 1}}) == {"k": {0: {"extra": True}}}
    assert _extra_fields_exclude({"plain": [1, "a"]}) is None
