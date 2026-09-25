"""Parsing ``custom_content.skills`` chips off the request messages."""

from aidial_sdk.chat_completion import Message, Role

from quickapp.skills.invocation._skill_reference import (
    collect_picks,
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


def _collect(messages: list[Message], max_per_message: int = 5):
    return collect_picks(messages, max_per_message)


class TestCollectPicks:

    def test_keys_picks_by_the_ordinal_of_the_user_message(self):
        messages = [
            _user("skills/b/a"),
            Message(role=Role.ASSISTANT, content="ok"),
            Message(role=Role.USER, content="plain"),
            _user("skills/b/z"),
        ]
        assert _collect(messages).by_ordinal == {0: ["skills/b/a"], 2: ["skills/b/z"]}

    def test_every_chip_of_a_message_is_loaded_in_order(self):
        collected = _collect([_user("skills/b/a", "skills/b/z")])

        assert collected.by_ordinal == {0: ["skills/b/a", "skills/b/z"]}

    def test_extra_chips_over_the_per_message_cap_are_reported_not_dropped_silently(self):
        collected = _collect([_user("skills/b/a", "skills/b/z", "skills/b/k")], max_per_message=2)

        assert collected.by_ordinal == {0: ["skills/b/a", "skills/b/z"]}
        assert collected.overflow_by_ordinal == {0: ["skills/b/k"]}

    def test_within_the_cap_reports_no_overflow(self):
        assert (
            _collect([_user("skills/b/a", "skills/b/z")], max_per_message=2).overflow_by_ordinal
            == {}
        )

    def test_a_repicked_url_keeps_its_first_pick(self):
        collected = _collect([_user("skills/b/a"), _user("skills/b/a")])

        assert collected.by_ordinal == {0: ["skills/b/a"]}

    def test_a_repicked_url_is_dropped_from_the_later_messages_chip_list(self):
        collected = _collect([_user("skills/b/a"), _user("skills/b/a", "skills/b/z")])

        assert collected.by_ordinal == {0: ["skills/b/a"], 1: ["skills/b/z"]}

    def test_no_chips_anywhere_yields_nothing(self):
        assert _collect([Message(role=Role.USER, content="hi")]).by_ordinal == {}


class TestSkillNameFromUrl:

    def test_uses_the_last_segment(self):
        assert skill_name_from_url("skills/bucket/nested/code-review") == "code-review"
