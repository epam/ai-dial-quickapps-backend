from aidial_sdk.chat_completion import Role

from quickapp.config.predefined_content_provider import (
    PredefinedContentProvider,
    PredefinedSettings,
)
from quickapp.skills._inject_file_transfer_instruction_transformer import (
    BUILTIN_FILE_TRANSFER_SKILL,
    SYNTHETIC_TOOL_CALL_ID,
    _InjectFileTransferInstructionTransformer,
)
from quickapp.skills._tool_configs import SKILL_READER_TOOL_NAME
from quickapp.skills.agent_skills_provider import AgentSkillsProvider


class TestInjectFileTransferInstructionTransformer:
    """Tests for _InjectFileTransferInstructionTransformer."""

    def test_skill_with_name_tool_call_file_parameter_formatting_is_present(self):
        """Verify the file-transfer skill is loaded and injected as a synthetic tool call."""
        provider = PredefinedContentProvider(PredefinedSettings())
        skills_provider = AgentSkillsProvider(provider)

        skill_content = skills_provider.get_skill_content(BUILTIN_FILE_TRANSFER_SKILL)
        assert skill_content
        assert BUILTIN_FILE_TRANSFER_SKILL in skill_content

        transformer = _InjectFileTransferInstructionTransformer(skills_provider)
        result = transformer.transform([])

        assert len(result) == 2, "Expected assistant tool call + tool response"

        assert result[0].role == Role.ASSISTANT
        assert result[0].tool_calls is not None
        assert len(result[0].tool_calls) == 1

        tool_call = result[0].tool_calls[0]
        assert tool_call.id == SYNTHETIC_TOOL_CALL_ID
        assert tool_call.function.name == SKILL_READER_TOOL_NAME
        assert BUILTIN_FILE_TRANSFER_SKILL in tool_call.function.arguments

        assert result[1].role == Role.TOOL
        assert result[1].tool_call_id == SYNTHETIC_TOOL_CALL_ID
        assert result[1].content is not None
        assert len(str(result[1].content)) > 0

        assert BUILTIN_FILE_TRANSFER_SKILL == "tool-call-file-parameter-formatting"
