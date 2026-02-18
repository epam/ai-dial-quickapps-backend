from pathlib import Path

from aidial_sdk.chat_completion import Role

from quickapp.config.config_template_resolver import PredefinedSettings
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
        """
        Test that the skill with name 'tool-call-file-parameter-formatting' is present
        in the skills directory and that the agent receives an injection with a synthetic tool call.
        """
        # Set up the real predefined settings pointing to the actual config directory
        project_root = Path(__file__).parents[4]  # Go up from tests/unit_tests/skills_tests to project root
        config_path = project_root / "config" / "predefined"

        predefined_settings = PredefinedSettings(base_path=str(config_path))

        # Create real skills provider with actual config
        skills_provider = AgentSkillsProvider(predefined_settings)

        # Verify the skill exists and can be loaded
        skill_content = skills_provider.get_skill_content(BUILTIN_FILE_TRANSFER_SKILL)
        assert skill_content is not None
        assert len(skill_content) > 0
        assert BUILTIN_FILE_TRANSFER_SKILL in skill_content

        # Create the transformer
        transformer = _InjectFileTransferInstructionTransformer(skills_provider)

        # Create empty message list (start of conversation)
        messages = []

        # Transform messages - should inject synthetic tool call
        result = transformer.transform(messages)

        # Verify injection happened
        assert len(result) == 2, "Should have 2 messages: assistant with tool call and tool response"

        # Verify first message is assistant with tool call
        assert result[0].role == Role.ASSISTANT
        assert result[0].tool_calls is not None
        assert len(result[0].tool_calls) == 1

        tool_call = result[0].tool_calls[0]
        assert tool_call.id == SYNTHETIC_TOOL_CALL_ID
        assert tool_call.function.name == SKILL_READER_TOOL_NAME
        assert BUILTIN_FILE_TRANSFER_SKILL in tool_call.function.arguments

        # Verify second message is tool response
        assert result[1].role == Role.TOOL
        assert result[1].tool_call_id == SYNTHETIC_TOOL_CALL_ID
        assert result[1].content is not None
        assert len(str(result[1].content)) > 0

        # Verify the constant value
        assert BUILTIN_FILE_TRANSFER_SKILL == "tool-call-file-parameter-formatting"


