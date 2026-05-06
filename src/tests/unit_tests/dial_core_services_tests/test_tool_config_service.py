from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aidial_client import DialException, ToolsetInfo
from pydantic import SecretStr

from quickapp.common.dial_settings import DialSettings
from quickapp.config.tools.const import ALL_MIME_TYPES
from quickapp.dial_core_services.exceptions import (
    ToolsetForbiddenException,
    ToolsetNotFoundException,
)
from quickapp.dial_core_services.tool_config_service import ToolConfigCoreService
from tests.unit_tests.common.common import noop_timeout_resolver_provider


def _make_dial_exception(status_code: int) -> DialException:
    exc = DialException.__new__(DialException)
    exc.status_code = status_code
    exc.message = f"HTTP {status_code}"
    return exc


def _make_deployment_model(
    deployment_id: str = "test-dep",
    description: str = "desc",
    input_attachment_types: list[str] | None = None,
    has_configuration: bool = False,
    display_name: str | None = None,
) -> MagicMock:
    features = MagicMock()
    features.configuration = has_configuration
    model = MagicMock()
    model.id = deployment_id
    model.display_name = display_name
    model.description = description
    model.input_attachment_types = input_attachment_types
    model.features = features
    return model


def _make_dial_settings() -> DialSettings:
    return DialSettings(url="https://dial-core", api_version="2025-01-01-preview")


def _make_service(dial_client: MagicMock) -> ToolConfigCoreService:
    provider = MagicMock()
    provider.get.return_value = dial_client
    return ToolConfigCoreService(
        dial_settings=_make_dial_settings(),
        dial_client_provider=provider,
        timeout_resolver_provider=noop_timeout_resolver_provider(),
    )


def _make_async_dial(
    deployment_model: MagicMock | None = None,
    application_model: MagicMock | None = None,
    deployments_get_side_effect: Exception | None = None,
    config_schema: dict | None = None,
    toolset_model: ToolsetInfo | None = None,
    toolset_side_effect: Exception | None = None,
) -> MagicMock:
    mock_deployments = MagicMock()
    mock_deployments.get = AsyncMock(
        return_value=deployment_model, side_effect=deployments_get_side_effect
    )
    mock_deployments.get_configuration_schema = AsyncMock(return_value=config_schema or {})

    mock_application = MagicMock()
    mock_application.get = AsyncMock(return_value=application_model)

    mock_toolset = MagicMock()
    mock_toolset.get = AsyncMock(return_value=toolset_model, side_effect=toolset_side_effect)

    dial_client = MagicMock()
    dial_client.deployments = mock_deployments
    dial_client.application = mock_application
    dial_client.toolset = mock_toolset
    return dial_client


class TestGetBasicToolConfig:
    @pytest.mark.asyncio
    async def test_returns_tool_config_for_deployment(self):
        dep = _make_deployment_model(deployment_id="gpt-4", has_configuration=False)
        dial_client = _make_async_dial(deployment_model=dep)
        svc = _make_service(dial_client)

        result = await svc.get_basic_tool_config("gpt-4")

        assert result.deployment.name == "gpt-4"
        dial_client.deployments.get.assert_awaited_once_with("gpt-4")
        dial_client.application.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_falls_back_to_application_on_404(self):
        app = _make_deployment_model(deployment_id="my-app")
        dial_client = _make_async_dial(
            deployments_get_side_effect=_make_dial_exception(404),
            application_model=app,
        )
        svc = _make_service(dial_client)

        result = await svc.get_basic_tool_config("my-app")

        assert result.deployment.name == "my-app"
        dial_client.application.get.assert_awaited_once_with("my-app")

    @pytest.mark.asyncio
    async def test_get_deployment_or_application_model_returns_deployment(self):
        dep = _make_deployment_model(deployment_id="gpt-4", has_configuration=False)
        dial_client = _make_async_dial(deployment_model=dep)
        svc = _make_service(dial_client)

        result = await svc.get_deployment_metadata("gpt-4")

        assert result is dep
        dial_client.deployments.get.assert_awaited_once_with("gpt-4")
        dial_client.application.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_deployment_or_application_model_falls_back_to_application(self):
        app = _make_deployment_model(deployment_id="my-app")
        dial_client = _make_async_dial(
            deployments_get_side_effect=_make_dial_exception(404),
            application_model=app,
        )
        svc = _make_service(dial_client)

        result = await svc.get_deployment_metadata("my-app")

        assert result is app
        dial_client.application.get.assert_awaited_once_with("my-app")

    @pytest.mark.asyncio
    async def test_non_404_dial_exception_propagates(self):
        dial_client = _make_async_dial(
            deployments_get_side_effect=_make_dial_exception(500),
        )
        svc = _make_service(dial_client)

        with pytest.raises(DialException):
            await svc.get_basic_tool_config("broken-dep")

    @pytest.mark.asyncio
    async def test_explicit_api_key_bypasses_provider(self):
        """Controller path: api_key comes from request header, not DI provider."""
        dep = _make_deployment_model(deployment_id="gpt-4")
        dial_client = _make_async_dial(deployment_model=dep)

        provider = MagicMock()
        svc = ToolConfigCoreService(
            dial_settings=_make_dial_settings(),
            dial_client_provider=provider,
            timeout_resolver_provider=noop_timeout_resolver_provider(),
        )

        with patch(
            "quickapp.dial_core_services.tool_config_service.AsyncDial", return_value=dial_client
        ):
            await svc.get_basic_tool_config("gpt-4", api_key=SecretStr("req-key"))

        provider.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_fetches_config_schema_when_features_enabled(self):
        dep = _make_deployment_model(has_configuration=True)
        schema = {"properties": {"lang": {"type": "string", "description": "Language"}}}
        dial_client = _make_async_dial(deployment_model=dep, config_schema=schema)
        svc = _make_service(dial_client)

        result = await svc.get_basic_tool_config("dep-with-config")

        dial_client.deployments.get_configuration_schema.assert_awaited_once()
        assert "lang" in result.open_ai_tool.function.parameters.properties


class TestGetBasicToolsetConfig:
    @pytest.mark.asyncio
    async def test_returns_toolset_info(self):
        toolset = MagicMock(spec=ToolsetInfo)
        dial_client = _make_async_dial(toolset_model=toolset)
        svc = _make_service(dial_client)

        result = await svc.get_basic_toolset_config("my-toolset")

        assert result is toolset
        dial_client.toolset.get.assert_awaited_once_with("my-toolset")

    @pytest.mark.asyncio
    async def test_raises_not_found_on_404(self):
        dial_client = _make_async_dial(toolset_side_effect=_make_dial_exception(404))
        svc = _make_service(dial_client)

        with pytest.raises(ToolsetNotFoundException):
            await svc.get_basic_toolset_config("missing")

    @pytest.mark.asyncio
    async def test_raises_forbidden_on_403(self):
        dial_client = _make_async_dial(toolset_side_effect=_make_dial_exception(403))
        svc = _make_service(dial_client)

        with pytest.raises(ToolsetForbiddenException):
            await svc.get_basic_toolset_config("forbidden")


def _make_deployment(
    deployment_id: str = "test-deployment",
    description: str = "A test deployment",
    input_attachment_types: list[str] | None = None,
    display_name: str | None = None,
):
    """Create a minimal deployment-like object for ToolConfigCoreService."""
    return SimpleNamespace(
        id=deployment_id,
        display_name=display_name,
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


class TestConvertToOpenaiToolFormatName:

    def test_display_name_used_as_tool_name_base(self):
        deployment = SimpleNamespace(
            id="applications/abc123/App%20with%20spaces__0.0.1",
            display_name="App with spaces",
            description="",
            input_attachment_types=None,
            features=None,
        )
        result = ToolConfigCoreService._convert_to_openai_tool_format(deployment)
        assert result.open_ai_tool.function.name == "App_with_spaces__0_0_1_tool"

    def test_tool_name_has_no_deployment_id_prefix(self):
        deployment = SimpleNamespace(
            id="applications/abc/my-app",
            display_name=None,
            description="",
            input_attachment_types=None,
            features=None,
        )
        result = ToolConfigCoreService._convert_to_openai_tool_format(deployment)
        assert result.open_ai_tool.function.name == "my-app_tool"
