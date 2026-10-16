from quickapp.config.tools.base import (
    ConfigurableSchemaConst,
    ConfigurableSchemaSimpleType,
    JsonTypeEnum,
    OpenAiToolConfig,
    OpenAiToolFunction,
    OpenAiToolFunctionParameters,
    remove_const_schema_params,
)


def _tool() -> OpenAiToolConfig:
    return OpenAiToolConfig(
        function=OpenAiToolFunction(
            name="search",
            description="Search issues",
            parameters=OpenAiToolFunctionParameters(
                type=JsonTypeEnum.object,
                properties={
                    "query": ConfigurableSchemaSimpleType(type=JsonTypeEnum.string),
                    "project_key": ConfigurableSchemaConst(type=None, const="DIAL"),
                    "limit": ConfigurableSchemaConst(type=None, const=50),
                },
                required=["query", "project_key"],
            ),
        )
    )


def test_drops_const_params_from_properties_and_required() -> None:
    parameters = remove_const_schema_params(_tool()).function.parameters

    assert list(parameters.properties) == ["query"]
    assert parameters.required == ["query"]


def test_leaves_missing_required_list_as_none() -> None:
    tool = _tool()
    tool.function.parameters.required = None

    assert remove_const_schema_params(tool).function.parameters.required is None


def test_does_not_mutate_input_tool() -> None:
    tool = _tool()

    remove_const_schema_params(tool)

    assert set(tool.function.parameters.properties) == {"query", "project_key", "limit"}
    assert tool.function.parameters.required == ["query", "project_key"]
