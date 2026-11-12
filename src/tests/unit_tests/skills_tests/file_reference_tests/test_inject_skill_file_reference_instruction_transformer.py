import pytest
from aidial_sdk.chat_completion import Message, Role

from quickapp.config.predefined_content_provider import (
    PredefinedContentProvider,
    PredefinedSettings,
)
from quickapp.skills.file_reference._inject_skill_file_reference_instruction_transformer import (
    BUILTIN_SKILL_FILE_REFERENCE_SKILL,
    _InjectSkillFileReferenceInstructionTransformer,
)
from quickapp.skills.registry._inject_file_transfer_instruction_transformer import (
    _InjectFileTransferInstructionTransformer,
)
from quickapp.skills.registry._tool_configs import SKILL_READER_TOOL_NAME
from quickapp.skills.registry.agent_skills_provider import AgentSkillsProvider
from tests.unit_tests.common.common import make_provider


def _skills_provider() -> AgentSkillsProvider:
    return AgentSkillsProvider(PredefinedContentProvider(PredefinedSettings()))


def _make_transformer() -> _InjectSkillFileReferenceInstructionTransformer:
    return _InjectSkillFileReferenceInstructionTransformer(
        _skills_provider(), enrichers_provider=make_provider([])
    )


def _assert_pair(messages: list[Message], assistant_idx: int, skill_name: str) -> None:
    assistant, tool = messages[assistant_idx], messages[assistant_idx + 1]

    assert assistant.role == Role.ASSISTANT
    assert assistant.tool_calls is not None and len(assistant.tool_calls) == 1
    assert assistant.tool_calls[0].function.name == SKILL_READER_TOOL_NAME
    assert skill_name in assistant.tool_calls[0].function.arguments
    assert tool.role == Role.TOOL
    assert tool.tool_call_id == assistant.tool_calls[0].id
    assert tool.content


class TestInjectSkillFileReferenceInstruction:

    @pytest.mark.asyncio
    async def test_injects_after_first_user_message(self):
        messages = [
            Message(role=Role.SYSTEM, content="system prompt"),
            Message(role=Role.USER, content="hello"),
        ]

        result = await _make_transformer().transform(messages)

        assert len(result) == 4
        assert result[1].role == Role.USER
        _assert_pair(result, 2, BUILTIN_SKILL_FILE_REFERENCE_SKILL)

    @pytest.mark.asyncio
    async def test_is_idempotent(self):
        transformer = _make_transformer()
        first = await transformer.transform([Message(role=Role.USER, content="hello")])

        second = await transformer.transform(first)

        assert second == first

    @pytest.mark.asyncio
    async def test_appends_at_end_without_user_message(self):
        result = await _make_transformer().transform(
            [Message(role=Role.SYSTEM, content="system prompt")]
        )

        assert len(result) == 3
        _assert_pair(result, 1, BUILTIN_SKILL_FILE_REFERENCE_SKILL)

    @pytest.mark.asyncio
    async def test_injected_text_teaches_the_reference_syntax(self):
        result = await _make_transformer().transform([Message(role=Role.USER, content="hi")])

        text = result[2].content
        assert "skill://" in text
        for prefix in ("file:url::", "file:text::", "file:base64::", "file:data::"):
            assert prefix in text

    @pytest.mark.asyncio
    async def test_coexists_with_the_file_transfer_instruction(self):
        skills = _skills_provider()
        file_transfer = _InjectFileTransferInstructionTransformer(
            skills, enrichers_provider=make_provider([])
        )
        messages = [Message(role=Role.USER, content="hello")]

        result = await _make_transformer().transform(await file_transfer.transform(messages))

        assert len(result) == 5
        call_ids = [m.tool_calls[0].id for m in result if m.tool_calls]
        assert len(set(call_ids)) == 2
        for idx, m in enumerate(result):
            if m.tool_calls:
                assert result[idx + 1].role == Role.TOOL
                assert result[idx + 1].tool_call_id == m.tool_calls[0].id
