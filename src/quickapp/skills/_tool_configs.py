from quickapp.common.tool_names import INTERNAL_SKILLS_READ_SKILL_TOOL_NAME
from quickapp.config.tools.base import (
    ConfigurableSchemaSimpleType,
    JsonTypeEnum,
    OpenAiToolConfig,
    OpenAiToolFunction,
    OpenAiToolFunctionParameters,
)
from quickapp.config.tools.display.paramenter import (
    FormattedParameterConfig,
    ParameterDisplayConfig,
)
from quickapp.config.tools.display.tool import ToolDisplayConfig, ToolStageConfig
from quickapp.config.tools.internal import InternalTool

SKILL_READER_TOOL_CONFIG = InternalTool(
    enabled=True,
    display=ToolDisplayConfig(
        stage=ToolStageConfig(
            name="Reading Skill: ",
            show=True,
        )
    ),
    open_ai_tool=OpenAiToolConfig(
        type="function",
        function=OpenAiToolFunction(
            name=INTERNAL_SKILLS_READ_SKILL_TOOL_NAME,
            description="Read the full content of an agent skill. Use this tool when you need to get detailed instructions about a specific skill that is available to you.",
            parameters=OpenAiToolFunctionParameters(
                type=JsonTypeEnum.object,
                properties={
                    "skill_name": ConfigurableSchemaSimpleType(
                        type=JsonTypeEnum.string,
                        description="The name of the skill to read. This should match the name from the available_skills list.",
                        display=ParameterDisplayConfig(
                            stage=FormattedParameterConfig(
                                show_value_in_stage_title=True,
                                ignore=True,
                            )
                        ),
                    )
                },
                required=["skill_name"],
            ),
        ),
    ),
)

SKILL_READER_TOOL_NAME = INTERNAL_SKILLS_READ_SKILL_TOOL_NAME
