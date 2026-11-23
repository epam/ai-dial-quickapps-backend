import pytest

from quickapp.config.tools.base import (
    ConfigurableSchemaObject,
    ConfigurableSchemaSimpleType,
    JsonTypeEnum,
    OpenAiToolConfig,
    OpenAiToolFunction,
    OpenAiToolFunctionParameters,
    to_llm_tool_dict,
)
from quickapp.config.tools.display.paramenter import (
    FormattedParameterConfig,
    ParameterDisplayConfig,
)
from quickapp.config.tools.internal import InternalTool
from quickapp.config.tools.rest_api import (
    RestApiEndpointHeaderParamInfo,
    RestApiEndpointSimpleTypeParam,
    ToolEndpointParamType,
)
from quickapp.dial_files_tooling._tool_configs import ALL_FILE_TOOL_CONFIGS

_JSON_SCHEMA_KEYWORDS = {
    "type",
    "description",
    "enum",
    "default",
    "properties",
    "required",
    "items",
}

_DISPLAY = ParameterDisplayConfig(stage=FormattedParameterConfig(show_value_in_stage_title=True))


def _tool(properties: dict, required: list[str] | None = None) -> OpenAiToolConfig:
    return OpenAiToolConfig(
        function=OpenAiToolFunction(
            name="weather",
            description="Current weather",
            parameters=OpenAiToolFunctionParameters(
                type=JsonTypeEnum.object, properties=properties, required=required
            ),
        )
    )


def test_hides_display_and_rest_parameter_info() -> None:
    tool = _tool(
        {
            "city": RestApiEndpointSimpleTypeParam(
                type=JsonTypeEnum.string,
                description="City name",
                default="Kyiv",
                display=_DISPLAY,
                parameter_info=RestApiEndpointHeaderParamInfo(
                    type=ToolEndpointParamType.query, key="q"
                ),
            )
        }
    )

    properties = to_llm_tool_dict(tool)["function"]["parameters"]["properties"]

    assert properties == {"city": {"type": "string", "description": "City name", "default": "Kyiv"}}


def test_keeps_nested_schema_and_tool_fields() -> None:
    tool = _tool(
        {
            "location": ConfigurableSchemaObject(
                type=JsonTypeEnum.object,
                description="Where",
                display=_DISPLAY,
                properties={
                    "lat": ConfigurableSchemaSimpleType(
                        type=JsonTypeEnum.number, default=0, display=_DISPLAY
                    ),
                },
                required=["lat"],
            )
        },
        required=["location"],
    )

    result = to_llm_tool_dict(tool)

    assert result == {
        "type": "function",
        "function": {
            "name": "weather",
            "description": "Current weather",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "object",
                        "description": "Where",
                        "properties": {"lat": {"type": "number", "default": 0}},
                        "required": ["lat"],
                    }
                },
                "required": ["location"],
            },
        },
    }


def test_does_not_change_the_tool_config() -> None:
    param = ConfigurableSchemaSimpleType(type=JsonTypeEnum.string, display=_DISPLAY)
    tool = _tool({"city": param})

    to_llm_tool_dict(tool)

    assert tool.function.parameters.properties["city"].display == _DISPLAY


@pytest.mark.parametrize(
    "tool_config", ALL_FILE_TOOL_CONFIGS, ids=lambda t: t.open_ai_tool.function.name
)
def test_file_tools_send_only_json_schema_keywords(tool_config: InternalTool) -> None:
    properties = to_llm_tool_dict(tool_config.open_ai_tool)["function"]["parameters"]["properties"]

    for param in properties.values():
        assert set(param) <= _JSON_SCHEMA_KEYWORDS
