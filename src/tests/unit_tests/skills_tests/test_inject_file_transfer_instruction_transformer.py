import pytest
from aidial_sdk.chat_completion import Message, Role

from quickapp.config.predefined_content_provider import (
    PredefinedContentProvider,
    PredefinedSettings,
)
from quickapp.skills._inject_file_transfer_instruction_transformer import (
    BUILTIN_FILE_TRANSFER_SKILL,
    _InjectFileTransferInstructionTransformer,
)
from quickapp.skills._tool_configs import SKILL_READER_TOOL_NAME
from quickapp.skills.agent_skills_provider import AgentSkillsProvider

EXPECTED_CALL_ID_NAME_START = f"synth_{SKILL_READER_TOOL_NAME}"


def _make_transformer() -> _InjectFileTransferInstructionTransformer:
    provider = PredefinedContentProvider(PredefinedSettings())
    skills_provider = AgentSkillsProvider(provider)
    return _InjectFileTransferInstructionTransformer(skills_provider)


def _assert_synthetic_pair(messages: list[Message], assistant_idx: int) -> None:
    """Assert that messages[assistant_idx] and messages[assistant_idx+1] form a valid synthetic pair."""
    assistant = messages[assistant_idx]
    tool = messages[assistant_idx + 1]

    assert assistant.role == Role.ASSISTANT
    assert assistant.tool_calls is not None
    assert len(assistant.tool_calls) == 1
    assert str(assistant.tool_calls[0].id).startswith(EXPECTED_CALL_ID_NAME_START)
    assert assistant.tool_calls[0].function.name == SKILL_READER_TOOL_NAME
    assert BUILTIN_FILE_TRANSFER_SKILL in assistant.tool_calls[0].function.arguments

    assert tool.role == Role.TOOL
    assert str(tool.tool_call_id).startswith(EXPECTED_CALL_ID_NAME_START)
    assert tool.content is not None
    assert tool.content


class TestInjectFileTransferInstructionTransformer:
    """Tests for _InjectFileTransferInstructionTransformer."""

    @pytest.mark.asyncio
    async def test_skill_with_name_tool_call_file_parameter_formatting_is_present(self):
        """Verify the file-transfer skill is loaded and injected as a synthetic tool call."""
        transformer = _make_transformer()
        result = await transformer.transform([])

        assert len(result) == 2, "Expected assistant tool call + tool response"
        _assert_synthetic_pair(result, 0)

    @pytest.mark.asyncio
    async def test_injects_after_first_user_message_with_system(self):
        """Synthetic pair is inserted after the first USER message, not after SYSTEM."""
        messages = [
            Message(role=Role.SYSTEM, content="system prompt"),
            Message(role=Role.USER, content="hello"),
        ]
        result = await _make_transformer().transform(messages)

        assert len(result) == 4
        assert result[0].role == Role.SYSTEM
        assert result[1].role == Role.USER
        _assert_synthetic_pair(result, 2)

    @pytest.mark.asyncio
    async def test_injects_after_first_user_message_without_system(self):
        """When there is no system message, inject after the first USER."""
        messages = [Message(role=Role.USER, content="hello")]
        result = await _make_transformer().transform(messages)

        assert len(result) == 3
        assert result[0].role == Role.USER
        _assert_synthetic_pair(result, 1)

    @pytest.mark.asyncio
    async def test_injects_after_first_user_with_multiple_users(self):
        """Synthetic pair is injected after the FIRST user message only."""
        messages = [
            Message(role=Role.SYSTEM, content="system prompt"),
            Message(role=Role.USER, content="first"),
            Message(role=Role.ASSISTANT, content="reply"),
            Message(role=Role.USER, content="second"),
        ]
        result = await _make_transformer().transform(messages)

        assert len(result) == 6
        assert result[0].role == Role.SYSTEM
        assert result[1].role == Role.USER
        assert result[1].content == "first"
        _assert_synthetic_pair(result, 2)
        assert result[4].role == Role.ASSISTANT
        assert result[4].content == "reply"
        assert result[5].role == Role.USER
        assert result[5].content == "second"

    @pytest.mark.asyncio
    async def test_no_user_message_appends_at_end(self):
        """When there is no USER message, synthetic pair is appended at the end."""
        messages = [Message(role=Role.SYSTEM, content="system prompt")]
        result = await _make_transformer().transform(messages)

        assert len(result) == 3
        assert result[0].role == Role.SYSTEM
        _assert_synthetic_pair(result, 1)

    @pytest.mark.asyncio
    async def test_skips_if_synthetic_already_present(self):
        """Transformer is idempotent — does not inject twice."""
        messages = [
            Message(role=Role.SYSTEM, content="system prompt"),
            Message(role=Role.USER, content="hello"),
        ]
        transformer = _make_transformer()
        first_pass = await transformer.transform(messages)
        second_pass = await transformer.transform(first_pass)

        assert len(second_pass) == len(first_pass)
        assert second_pass == first_pass
