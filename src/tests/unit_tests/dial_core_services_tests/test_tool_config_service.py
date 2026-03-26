from types import SimpleNamespace

from quickapp.config.tools.const import ALL_MIME_TYPES
from quickapp.dial_core_services.tool_config_service import ToolConfigCoreService


def _make_deployment(
    deployment_id: str = "test-deployment",
    description: str = "A test deployment",
    input_attachment_types: list[str] | None = None,
):
    """Create a minimal deployment-like object for ToolConfigCoreService."""
    return SimpleNamespace(
        id=deployment_id,
        description=description,
        input_attachment_types=input_attachment_types,
        features=None,
    )


def test_supported_types_defaults_to_all_when_no_input_attachment_types():
    deployment = _make_deployment(input_attachment_types=None)
    result = ToolConfigCoreService._convert_to_openai_tool_format(deployment)

    assert result.attachment.supported_types == [ALL_MIME_TYPES]


def test_supported_types_defaults_to_all_when_empty_input_attachment_types():
    deployment = _make_deployment(input_attachment_types=[])
    result = ToolConfigCoreService._convert_to_openai_tool_format(deployment)

    # Even with empty input_attachment_types, supported_types should default to all
    assert result.attachment.supported_types == [ALL_MIME_TYPES]


def test_propagate_types_to_choice_is_default_for_deployment_tools():
    deployment = _make_deployment(input_attachment_types=["image/*"])
    result = ToolConfigCoreService._convert_to_openai_tool_format(deployment)

    assert len(result.attachment.propagate_types_to_choice) == 2
    assert "image/*" in result.attachment.propagate_types_to_choice
    assert "application/vnd.plotly.v1+json" in result.attachment.propagate_types_to_choice


def test_input_attachment_types_adds_attachment_urls_param():
    deployment = _make_deployment(input_attachment_types=["image/*"])
    result = ToolConfigCoreService._convert_to_openai_tool_format(deployment)

    assert "attachment_urls" in result.open_ai_tool.function.parameters.properties


def test_no_input_attachment_types_no_attachment_urls_param():
    deployment = _make_deployment(input_attachment_types=None)
    result = ToolConfigCoreService._convert_to_openai_tool_format(deployment)

    assert "attachment_urls" not in result.open_ai_tool.function.parameters.properties


def test_config_schema_populates_configuration_param_names():
    deployment = _make_deployment()
    config = {
        "properties": {
            "size": {"type": "string", "description": "Image size"},
            "quality": {"type": "string", "description": "Image quality"},
        },
        "required": ["size"],
    }
    result = ToolConfigCoreService._convert_to_openai_tool_format(deployment, config)

    assert result.deployment._configuration_param_names == {"size", "quality"}


def test_no_config_leaves_configuration_param_names_empty():
    deployment = _make_deployment()
    result = ToolConfigCoreService._convert_to_openai_tool_format(deployment)

    assert result.deployment._configuration_param_names == set()


def test_config_without_properties_leaves_configuration_param_names_empty():
    deployment = _make_deployment()
    config = {"required": ["size"]}
    result = ToolConfigCoreService._convert_to_openai_tool_format(deployment, config)

    assert result.deployment._configuration_param_names == set()
