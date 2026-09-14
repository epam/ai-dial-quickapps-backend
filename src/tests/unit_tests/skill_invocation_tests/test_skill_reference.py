"""Parsing ``custom_content.skills`` chips off the request messages."""

from aidial_sdk.chat_completion import Message, Role

from quickapp.skill_invocation._skill_reference import (
    collect_skill_urls,
    message_skill_urls,
    skill_name_from_url,
)


def _user(*urls: str, **extra) -> Message:
    custom_content = {"skills": [{"url": url} for url in urls], **extra}
    return Message.model_validate(
        {"role": "user", "content": "hi", "custom_content": custom_content}
    )


class TestMessageSkillUrls:

    def test_reads_urls_in_chip_order(self):
        assert message_skill_urls(_user("skills/b/a", "skills/b/z")) == [
            "skills/b/a",
            "skills/b/z",
        ]

    def test_strips_a_trailing_slash(self):
        assert message_skill_urls(_user("skills/b/a/")) == ["skills/b/a"]

    def test_identical_chips_count_once(self):
        assert message_skill_urls(_user("skills/b/a", "skills/b/a/")) == ["skills/b/a"]

    def test_a_message_without_chips_yields_nothing(self):
        assert message_skill_urls(Message(role=Role.USER, content="hi")) == []

    def test_chips_on_a_non_user_message_are_ignored(self):
        message = _user("skills/b/a")
        message.role = Role.ASSISTANT
        assert message_skill_urls(message) == []

    def test_malformed_entries_are_dropped(self):
        message = Message.model_validate(
            {
                "role": "user",
                "content": "hi",
                "custom_content": {"skills": ["skills/b/a", {}, {"url": 7}, {"url": "skills/b/k"}]},
            }
        )
        assert message_skill_urls(message) == ["skills/b/k"]

    def test_a_non_list_field_is_ignored(self):
        message = Message.model_validate(
            {"role": "user", "content": "hi", "custom_content": {"skills": "skills/b/a"}}
        )
        assert message_skill_urls(message) == []

    def test_other_chip_fields_are_ignored(self):
        message = Message.model_validate(
            {
                "role": "user",
                "content": "hi",
                "custom_content": {"skills": [{"url": "skills/b/a", "title": "A"}]},
            }
        )
        assert message_skill_urls(message) == ["skills/b/a"]


class TestCollectSkillUrls:

    def test_returns_conversation_picks_oldest_first(self):
        messages = [
            _user("skills/b/a"),
            Message(role=Role.ASSISTANT, content="ok"),
            _user("skills/b/z"),
        ]
        assert collect_skill_urls(messages, 10) == ["skills/b/a", "skills/b/z"]

    def test_a_repicked_url_moves_to_the_end(self):
        messages = [_user("skills/b/a"), _user("skills/b/z"), _user("skills/b/a")]
        assert collect_skill_urls(messages, 10) == ["skills/b/z", "skills/b/a"]

    def test_the_cap_drops_the_oldest_picks(self):
        messages = [_user("skills/b/a"), _user("skills/b/z"), _user("skills/b/k")]
        assert collect_skill_urls(messages, 2) == ["skills/b/z", "skills/b/k"]

    def test_no_chips_anywhere_yields_nothing(self):
        assert collect_skill_urls([Message(role=Role.USER, content="hi")], 10) == []


class TestSkillNameFromUrl:

    def test_uses_the_last_segment(self):
        assert skill_name_from_url("skills/bucket/nested/code-review") == "code-review"
